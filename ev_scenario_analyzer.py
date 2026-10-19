import json
import time
import argparse
from pathlib import Path

import numpy as np
import pandapower as pp

from gridguard_net_builder import (
    build_network, run_robust_powerflow, add_common_args, units_from_args,
)

BASE_DIR = Path(__file__).resolve().parent
SUMMARY_FILE = BASE_DIR / "ev_scenario_summary.json"

VOLTAGE_LIMIT = 0.90        # pu
N_SEEDS = 5                 # random charging-start patterns per scenario
RISK_THRESHOLD_PCT = 20.0   # a scenario passes if at most this share of patterns violate
MAX_EVS = 2000              # upper bound of the capacity search
EV_MW = 0.0072              # 7.2 kW per charging EV
EV_Q_RATIO = 0.2            # reactive power as a fraction of active power
CHARGE_HOURS = 3
START_MIN, START_MAX = 16, 21   # EVs start charging between 16:00 and 21:00
N_WEAK_BUSES = 3


def load_factor(h):
    return 0.6 + 0.4 * np.cos((h - 18) * np.pi / 12)


def candidate_hours():
    """Hours that can possibly give the worst voltage.

    An hour is skipped when another hour has at least the same base-load factor
    AND at least the same set of charging EVs, because more load can never give
    a higher minimum voltage on a passive feeder. With the default settings this
    leaves hours 18, 19, 20 and 21 instead of all 24.
    """
    starts = range(START_MIN, START_MAX + 1)
    charging = {h: frozenset(s for s in starts if s <= h < s + CHARGE_HOURS) for h in range(24)}
    lf = {h: load_factor(h) for h in range(24)}
    keep = []
    for h in range(24):
        dominated = any(
            g != h and charging[h] <= charging[g] and lf[h] <= lf[g]
            and (charging[h] < charging[g] or lf[h] < lf[g] or g < h)
            for g in range(24)
        )
        if not dominated:
            keep.append(h)
    return keep


HOURS = candidate_hours()
_PF_CACHE = {}   # (hour, number of charging EVs) -> (converged, min voltage)


def pick_weak_buses(net, n=N_WEAK_BUSES):
    """The electrically weakest buses: lowest base-case voltage, source excluded."""
    vm = net.res_bus.vm_pu.drop(net.ext_grid.bus.values, errors="ignore").dropna()
    return [int(b) for b in vm.sort_values().index[:n]]


def simulate(net, n_evs, seed, weak_buses, limit, stop_on_violation=False):
    """One simulated day. Non-converged hours count as violations.

    The network state depends only on the hour and on how many EVs are
    charging, so power flow results are cached by that pair.
    """
    rng = np.random.default_rng(seed)
    starts = (rng.integers(START_MIN, START_MAX + 1, size=n_evs)
              if n_evs > 0 else np.array([], dtype=int))

    base_index = net.load.index.copy()
    base_p = net.load.loc[base_index, "p_mw"].values.copy()
    base_q = net.load.loc[base_index, "q_mvar"].values.copy()

    ev_idx = []
    if n_evs > 0 and weak_buses:
        for b in weak_buses:
            ev_idx.append(pp.create_load(net, bus=b, p_mw=0.0, q_mvar=0.0, name="EV_Temp"))

    volts, failed_hours = [], 0
    try:
        for h in HOURS:
            active = int(np.sum((starts <= h) & (h < starts + CHARGE_HOURS))) if ev_idx else 0
            key = (h, active)
            if key in _PF_CACHE:
                ok, v = _PF_CACHE[key]
            else:
                lf = load_factor(h)
                net.load.loc[base_index, "p_mw"] = base_p * lf
                net.load.loc[base_index, "q_mvar"] = base_q * lf
                if ev_idx:
                    p_ev = active * EV_MW / len(ev_idx)
                    net.load.loc[ev_idx, "p_mw"] = p_ev
                    net.load.loc[ev_idx, "q_mvar"] = p_ev * EV_Q_RATIO
                ok = run_robust_powerflow(net)
                v = float(np.nanmin(net.res_bus.vm_pu.values)) if ok else None
                _PF_CACHE[key] = (ok, v)

            if ok:
                volts.append(v)
                if stop_on_violation and v < limit:
                    break
            else:
                failed_hours += 1
                if stop_on_violation:
                    break
    finally:
        if ev_idx:
            net.load.drop(ev_idx, inplace=True)
        net.load.loc[base_index, "p_mw"] = base_p
        net.load.loc[base_index, "q_mvar"] = base_q

    min_v = min(volts) if volts else None
    violated = failed_hours > 0 or (min_v is not None and min_v < limit)
    return {"min_v": min_v, "failed_hours": failed_hours, "violated": violated}


def evaluate(net, n_evs, weak_buses, limit, early=False):
    """Run all seeds. With early=True stop as soon as the scenario must fail."""
    violations, failed_hours, worst = 0, 0, None
    for seed in range(N_SEEDS):
        res = simulate(net, n_evs, seed, weak_buses, limit, stop_on_violation=early)
        violations += int(res["violated"])
        failed_hours += res["failed_hours"]
        if res["min_v"] is not None and (worst is None or res["min_v"] < worst):
            worst = res["min_v"]
        if early and violations * 100.0 / N_SEEDS > RISK_THRESHOLD_PCT:
            break
    prob = violations * 100.0 / N_SEEDS
    return {"prob": prob, "worst": worst, "failed_hours": failed_hours,
            "passes": prob <= RISK_THRESHOLD_PCT}


def write_failure(message):
    SUMMARY_FILE.write_text(json.dumps({
        "status": "FAIL", "error": message,
        "exact_max_hosting_capacity": 0, "scenarios": [],
    }, indent=2))
    print(f"EV analysis not possible: {message}")


def main():
    global HOURS
    parser = argparse.ArgumentParser()
    add_common_args(parser)
    parser.add_argument("--full-day", action="store_true",
                        help="Simulate all 24 hours instead of only the worst candidate hours (slower)")
    args = parser.parse_args()
    if args.full_day:
        HOURS = list(range(24))

    started = time.time()
    _PF_CACHE.clear()

    net = build_network(args.buses_csv, args.lines_csv, units_from_args(args))

    if not run_robust_powerflow(net):
        write_failure("The base-case power flow did not converge. " + net.get("gg_pf_error", ""))
        return

    weak = pick_weak_buses(net)
    weak_names = [str(net.bus.at[b, "name"]) for b in weak]

    baseline = evaluate(net, 0, weak, VOLTAGE_LIMIT)
    baseline_violation = not baseline["passes"]

    exact_max = 0
    if not baseline_violation:
        low, high = 0, MAX_EVS
        while low <= high:
            mid = (low + high) // 2
            if evaluate(net, mid, weak, VOLTAGE_LIMIT, early=True)["passes"]:
                exact_max = mid
                low = mid + 1
            else:
                high = mid - 1
    capped = (not baseline_violation) and exact_max >= MAX_EVS

    if exact_max > 0:
        scenarios = {0, exact_max, round(exact_max * 0.25), round(exact_max * 0.5),
                     round(exact_max * 0.75)}
        if not capped:
            scenarios |= {round(exact_max * 1.25), round(exact_max * 1.5)}
    else:
        scenarios = {0, 10, 25, 50, 100}
    scenarios = sorted(int(s) for s in scenarios)

    results = []
    for evs in scenarios:
        ev_res = evaluate(net, evs, weak, VOLTAGE_LIMIT)
        if evs == exact_max and not baseline_violation:
            status = "EXACT LIMIT"
        else:
            status = "PASS" if ev_res["passes"] else "FAIL"
        results.append({
            "ev_count": evs,
            "worst_min_voltage": None if ev_res["worst"] is None else round(float(ev_res["worst"]), 4),
            "violation_probability_pct": ev_res["prob"],
            "failed_hours": ev_res["failed_hours"],
            "status": status,
        })

    summary = {
        "status": "REVIEW" if baseline_violation else "PASS",
        "exact_max_hosting_capacity": exact_max,
        "baseline_violation": baseline_violation,
        "capped": capped,
        "max_evs_searched": MAX_EVS,
        "voltage_limit_pu": VOLTAGE_LIMIT,
        "risk_threshold_pct": RISK_THRESHOLD_PCT,
        "seeds": N_SEEDS,
        "hours_simulated": HOURS,
        "weak_buses": weak_names,
        "scenarios": results,
    }
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2))
    print(f"EV analysis complete in {time.time() - started:.1f}s. "
          f"Exact hosting capacity: {exact_max} EVs "
          f"({len(_PF_CACHE)} distinct power flows)")


if __name__ == "__main__":
    main()