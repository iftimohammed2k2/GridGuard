import argparse
import copy
import csv
import json
import math
from pathlib import Path

import pandapower as pp
import pandapower.networks as pn


BASE_DIR = Path(__file__).resolve().parent

SUMMARY_CSV = BASE_DIR / "ev_scenario_summary.csv"
BUS_RESULTS_CSV = BASE_DIR / "ev_scenario_bus_results.csv"
SUMMARY_JSON = BASE_DIR / "ev_scenario_summary.json"
REPORT_TXT = BASE_DIR / "ev_scenario_report.txt"

# Default IEEE 33-bus benchmark connection points (bus indices 0–32).
EV_CONNECTION_BUSES = [18, 25, 30]

EV_CHARGER_KW = 7.2
EV_POWER_FACTOR = 0.98

VOLTAGE_MIN_PU = 0.95
VOLTAGE_MAX_PU = 1.05

# Conservative sanity check only; not a universal engineering limit.
# The case33bw benchmark contains placeholder ratings that should not be
# interpreted as real equipment ratings.
MAX_PLAUSIBLE_LINE_RATING_KA = 1000.0

DEFAULT_SCENARIOS = [0, 10, 25, 50]


def finite_number(value):
    """Return True if value can be interpreted as a finite number."""
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def distribute_evs(total_evs, bus_ids):
    """Distribute EVs as evenly as possible over selected buses."""
    if isinstance(total_evs, bool) or not isinstance(total_evs, int):
        raise ValueError("total_evs must be a non-negative integer.")
    if total_evs < 0:
        raise ValueError("total_evs cannot be negative.")
    if not bus_ids:
        if total_evs == 0:
            return {}
        raise ValueError("At least one connection bus is required.")
    if len(set(bus_ids)) != len(bus_ids):
        raise ValueError("Connection bus IDs must be unique.")

    base_count, remainder = divmod(total_evs, len(bus_ids))
    return {
        bus_id: base_count + (1 if index < remainder else 0)
        for index, bus_id in enumerate(bus_ids)
    }


def validate_inputs(net, scenario_counts, bus_ids, charger_kw, power_factor):
    """Validate user-supplied EV scenario settings."""
    if not scenario_counts:
        raise ValueError("Provide at least one EV scenario.")
    if any(isinstance(count, bool) or not isinstance(count, int) for count in scenario_counts):
        raise ValueError("EV counts must be integers.")
    if any(count < 0 for count in scenario_counts):
        raise ValueError("EV counts cannot be negative.")
    if len(set(scenario_counts)) != len(scenario_counts):
        raise ValueError("EV scenario counts must be unique.")

    if not bus_ids:
        raise ValueError("At least one EV connection bus is required.")
    if any(isinstance(bus_id, bool) or not isinstance(bus_id, int) for bus_id in bus_ids):
        raise ValueError("EV connection bus IDs must be integers.")
    if len(set(bus_ids)) != len(bus_ids):
        raise ValueError("EV connection bus IDs must be unique.")

    for bus_id in bus_ids:
        if bus_id not in net.bus.index:
            raise ValueError(f"Unknown EV connection bus: {bus_id}")
        if not bool(net.bus.at[bus_id, "in_service"]):
            raise ValueError(f"EV connection bus {bus_id} is out of service.")

    if not finite_number(charger_kw) or float(charger_kw) <= 0:
        raise ValueError("charger_kw must be a positive finite number.")
    if not finite_number(power_factor) or not 0 < float(power_factor) <= 1:
        raise ValueError("power_factor must be in the range (0, 1].")


def add_ev_loads(net, total_evs, bus_ids, charger_kw, power_factor):
    """Add constant-P/Q EV charging loads to a pandapower network."""
    allocation = distribute_evs(total_evs, bus_ids)
    if total_evs == 0:
        return allocation

    p_mw_per_ev = float(charger_kw) / 1000.0
    q_mvar_per_ev = p_mw_per_ev * math.tan(math.acos(float(power_factor)))

    for bus_id, ev_count in allocation.items():
        if ev_count == 0:
            continue
        pp.create_load(
            net,
            bus=bus_id,
            p_mw=ev_count * p_mw_per_ev,
            q_mvar=ev_count * q_mvar_per_ev,
            name=f"GridGuard EV charging at bus {bus_id}",
            type="ev_charging",
        )
    return allocation


def run_power_flow(net):
    """Run an AC Newton–Raphson power flow."""
    try:
        pp.runpp(
            net,
            algorithm="nr",
            numba=False,
            init="auto",
            max_iteration=50,
        )
        if net.converged:
            return True, None
        return False, "Power flow did not converge."
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def get_line_loading_assessment(net):
    """Assess line loading only when equipment ratings appear usable."""
    assessed = 0
    unassessable = 0
    overloads = 0
    maximum_loading = None

    for line_id, line in net.line.iterrows():
        if not bool(line.get("in_service", True)):
            continue

        rating = line.get("max_i_ka")
        derating = line.get("df", 1.0)
        parallel = line.get("parallel", 1)

        try:
            parallel_float = float(parallel)
        except (TypeError, ValueError, OverflowError):
            parallel_float = float("nan")

        rating_valid = (
            finite_number(rating)
            and 0 < float(rating) < MAX_PLAUSIBLE_LINE_RATING_KA
            and finite_number(derating)
            and 0 < float(derating) <= 1
            and math.isfinite(parallel_float)
            and parallel_float > 0
            and parallel_float.is_integer()
        )

        if not rating_valid or line_id not in net.res_line.index:
            unassessable += 1
            continue

        loading = net.res_line.at[line_id, "loading_percent"]
        if not finite_number(loading) or float(loading) < 0:
            unassessable += 1
            continue

        loading = float(loading)
        assessed += 1
        maximum_loading = loading if maximum_loading is None else max(maximum_loading, loading)
        if loading > 100.0:
            overloads += 1

    return {
        "lines_assessed": assessed,
        "lines_unassessable": unassessable,
        "line_overloads": overloads,
        "max_assessed_line_loading_percent": maximum_loading,
    }


def analyze_scenario(
    net,
    ev_count,
    bus_ids=EV_CONNECTION_BUSES,
    charger_kw=EV_CHARGER_KW,
    power_factor=EV_POWER_FACTOR,
):
    """Analyze one EV scenario using an isolated copy of the network."""
    working_net = copy.deepcopy(net)
    allocation = add_ev_loads(working_net, ev_count, bus_ids, charger_kw, power_factor)
    converged, error = run_power_flow(working_net)

    result = {
        "ev_count": ev_count,
        "charger_kw": float(charger_kw),
        "power_factor": float(power_factor),
        "total_ev_power_mw": ev_count * float(charger_kw) / 1000.0,
        "ev_allocation": {str(bus): count for bus, count in allocation.items()},
        "converged": converged,
        "error": error,
        "status": "FAIL" if not converged else "PENDING",
        "min_voltage_pu": None,
        "max_voltage_pu": None,
        "min_voltage_change_pu": None,
        "low_voltage_bus_count": None,
        "high_voltage_bus_count": None,
        "voltage_violation_bus_ids": [],
        "new_voltage_violation_bus_ids": [],
        "total_active_load_mw": None,
        "active_losses_mw": None,
        "lines_assessed": 0,
        "lines_unassessable": 0,
        "line_overloads": None,
        "max_assessed_line_loading_percent": None,
        "bus_results": [],
    }

    if not converged:
        return result

    active_buses = working_net.bus.index[working_net.bus["in_service"].astype(bool)]
    bus_results = []
    for bus_id in active_buses:
        vm = float(working_net.res_bus.at[bus_id, "vm_pu"])
        bus_results.append({
            "ev_count": ev_count,
            "bus_id": int(bus_id),
            "voltage_pu": vm,
            "below_minimum": vm < VOLTAGE_MIN_PU,
            "above_maximum": vm > VOLTAGE_MAX_PU,
        })

    voltages = [row["voltage_pu"] for row in bus_results]
    low_buses = [row["bus_id"] for row in bus_results if row["below_minimum"]]
    high_buses = [row["bus_id"] for row in bus_results if row["above_maximum"]]

    result["bus_results"] = bus_results
    result["min_voltage_pu"] = min(voltages)
    result["max_voltage_pu"] = max(voltages)
    result["low_voltage_bus_count"] = len(low_buses)
    result["high_voltage_bus_count"] = len(high_buses)
    result["voltage_violation_bus_ids"] = sorted(set(low_buses + high_buses))
    result["total_active_load_mw"] = float(working_net.res_load["p_mw"].sum())
    result["active_losses_mw"] = float(
        working_net.res_line["pl_mw"].sum() + working_net.res_trafo["pl_mw"].sum()
    )
    result.update(get_line_loading_assessment(working_net))

    if result["low_voltage_bus_count"] > 0 or result["high_voltage_bus_count"] > 0:
        result["status"] = "REVIEW"
    elif result["line_overloads"] and result["line_overloads"] > 0:
        result["status"] = "REVIEW"
    elif result["lines_unassessable"] > 0:
        result["status"] = "INCOMPLETE"
    else:
        result["status"] = "PASS"

    return result


def compare_with_baseline(results):
    """Compare each scenario with the zero-EV baseline."""
    baseline = next((row for row in results if row["ev_count"] == 0), None)
    if baseline is None or not baseline["converged"]:
        for row in results:
            row["min_voltage_change_pu"] = None
            row["new_voltage_violation_bus_ids"] = []
        return results

    baseline_violations = set(baseline["voltage_violation_bus_ids"])
    baseline_min = baseline["min_voltage_pu"]

    for row in results:
        row["min_voltage_change_pu"] = (
            row["min_voltage_pu"] - baseline_min if row["converged"] else None
        )
        row["new_voltage_violation_bus_ids"] = (
            sorted(set(row["voltage_violation_bus_ids"]) - baseline_violations)
            if row["converged"] else []
        )
    return results


def save_outputs(results, output_dir=None):
    """Write scenario CSV, per-bus CSV, JSON summary, and text report."""
    output_dir = Path(output_dir) if output_dir is not None else BASE_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_csv = output_dir / SUMMARY_CSV.name
    bus_results_csv = output_dir / BUS_RESULTS_CSV.name
    summary_json = output_dir / SUMMARY_JSON.name
    report_txt = output_dir / REPORT_TXT.name

    summary_fields = [
        "ev_count", "charger_kw", "power_factor", "total_ev_power_mw",
        "converged", "status", "min_voltage_pu", "max_voltage_pu",
        "min_voltage_change_pu", "low_voltage_bus_count", "high_voltage_bus_count",
        "voltage_violation_bus_ids", "new_voltage_violation_bus_ids",
        "total_active_load_mw", "active_losses_mw", "lines_assessed",
        "lines_unassessable", "line_overloads", "max_assessed_line_loading_percent", "error",
    ]

    with summary_csv.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=summary_fields)
        writer.writeheader()
        for row in results:
            record = {key: row.get(key) for key in summary_fields}
            for key in ("voltage_violation_bus_ids", "new_voltage_violation_bus_ids"):
                record[key] = json.dumps(record[key])
            writer.writerow(record)

    bus_fields = ["ev_count", "bus_id", "voltage_pu", "below_minimum", "above_maximum"]
    with bus_results_csv.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=bus_fields)
        writer.writeheader()
        for scenario in results:
            writer.writerows(scenario["bus_results"])

    compact_results = [{key: value for key, value in row.items() if key != "bus_results"} for row in results]
    summary_json.write_text(json.dumps(compact_results, indent=2), encoding="utf-8")

    lines = [
        "=" * 72,
        "GRIDGUARD - EV CHARGING SCENARIO ANALYSIS",
        "=" * 72,
        f"Voltage limits: {VOLTAGE_MIN_PU:.2f}–{VOLTAGE_MAX_PU:.2f} p.u.",
        f"EV charger rating: {results[0]['charger_kw']:.2f} kW" if results else "EV charger rating: N/A",
        f"Assumed power factor: {results[0]['power_factor']:.2f}" if results else "Assumed power factor: N/A",
        f"Connection buses: {results[0]['ev_allocation'] if results else {}}",
        "",
    ]

    for row in results:
        lines.extend([
            "-" * 72,
            f"EVs: {row['ev_count']}",
            f"Added EV active power: {row['total_ev_power_mw']:.4f} MW",
            f"Power flow converged: {row['converged']}",
            f"Scenario status: {row['status']}",
        ])
        if not row["converged"]:
            lines.append(f"Error: {row['error']}")
            continue
        lines.extend([
            f"Minimum voltage: {row['min_voltage_pu']:.4f} p.u.",
            f"Maximum voltage: {row['max_voltage_pu']:.4f} p.u.",
            f"Minimum voltage change vs baseline: {row['min_voltage_change_pu']:+.4f} p.u."
            if row["min_voltage_change_pu"] is not None else "Minimum voltage change vs baseline: N/A",
            f"Buses below {VOLTAGE_MIN_PU:.2f} p.u.: {row['low_voltage_bus_count']}",
            f"Buses above {VOLTAGE_MAX_PU:.2f} p.u.: {row['high_voltage_bus_count']}",
            f"Voltage violation bus IDs: {row['voltage_violation_bus_ids']}",
            f"New violation bus IDs vs baseline: {row['new_voltage_violation_bus_ids']}",
            f"Active losses: {row['active_losses_mw']:.6f} MW",
            f"Lines with assessable ratings: {row['lines_assessed']}",
            f"Lines not assessable: {row['lines_unassessable']}",
            f"Assessed line overloads: {row['line_overloads']}",
        ])

    lines.extend([
        "",
        "IMPORTANT LIMITATIONS",
        "- Steady-state AC power flow only; this is not a time-series study.",
        "- EV counts are distributed evenly over configured connection buses.",
        "- Charging is represented as constant active/reactive power.",
        "- Placeholder benchmark line ratings are not treated as real ratings.",
        "- INCOMPLETE means some equipment-rating checks cannot be assessed.",
        "- Results depend on the benchmark, assumptions, and voltage thresholds.",
        "=" * 72,
    ])
    report_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_analysis(
    scenario_counts=None,
    bus_ids=None,
    charger_kw=EV_CHARGER_KW,
    power_factor=EV_POWER_FACTOR,
):
    """Run requested scenarios against the same benchmark network."""
    if scenario_counts is None:
        scenario_counts = DEFAULT_SCENARIOS.copy()
    else:
        scenario_counts = list(scenario_counts)
    if bus_ids is None:
        bus_ids = EV_CONNECTION_BUSES.copy()
    else:
        bus_ids = list(bus_ids)

    base_net = pn.case33bw()
    validate_inputs(base_net, scenario_counts, bus_ids, charger_kw, power_factor)

    # Always add zero-EV baseline, regardless of user selection.
    scenarios = sorted(set(scenario_counts) | {0})
    results = [
        analyze_scenario(
            base_net, ev_count, bus_ids=bus_ids,
            charger_kw=charger_kw, power_factor=power_factor,
        )
        for ev_count in scenarios
    ]
    return compare_with_baseline(results)


def parse_int_list(value, label):
    try:
        values = [int(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{label} must be comma-separated integers.") from exc
    if not values:
        raise argparse.ArgumentTypeError(f"{label} cannot be empty.")
    if len(values) != len(set(values)):
        raise argparse.ArgumentTypeError(f"{label} must not contain duplicates.")
    return values


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run GridGuard EV charging scenarios on pandapower's IEEE 33-bus benchmark."
    )
    parser.add_argument(
        "--ev-counts", default=",".join(map(str, DEFAULT_SCENARIOS)),
        help="Comma-separated EV counts, e.g. 0,10,25,50 (default: 0,10,25,50).",
    )
    parser.add_argument(
        "--buses", default=",".join(map(str, EV_CONNECTION_BUSES)),
        help="Comma-separated zero-based bus IDs, e.g. 18,25,30.",
    )
    parser.add_argument("--charger-kw", type=float, default=EV_CHARGER_KW, help="Charger rating in kW.")
    parser.add_argument("--power-factor", type=float, default=EV_POWER_FACTOR, help="Power factor, >0 and <=1.")
    args = parser.parse_args(argv)

    try:
        scenario_counts = parse_int_list(args.ev_counts, "EV counts")
        bus_ids = parse_int_list(args.buses, "Bus IDs")
        results = run_analysis(
            scenario_counts=scenario_counts,
            bus_ids=bus_ids,
            charger_kw=args.charger_kw,
            power_factor=args.power_factor,
        )
        save_outputs(results)
    except (ValueError, TypeError) as exc:
        parser.error(str(exc))

    for row in results:
        min_v = f"{row['min_voltage_pu']:.4f}" if row["converged"] else "N/A"
        low_count = row["low_voltage_bus_count"] if row["converged"] else "N/A"
        print(
            f"EVs={row['ev_count']:>3} | Converged={row['converged']} | "
            f"Min voltage={min_v} p.u. | Low-voltage buses={low_count} | "
            f"Status={row['status']}"
        )

    print(f"\nSummary CSV: {SUMMARY_CSV}")
    print(f"Bus results CSV: {BUS_RESULTS_CSV}")
    print(f"Summary JSON: {SUMMARY_JSON}")
    print(f"Report TXT: {REPORT_TXT}")

    # Engineering REVIEW/INCOMPLETE findings are not software crashes.
    return 0 if all(row["converged"] for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())