import math
import sys
from pathlib import Path

import pandas as pd
import pandapower as pp
import pandapower.networks as pn

OUT = Path(__file__).resolve().parent
RATING_KA = 0.25       # DEMO ASSUMPTION, not verified asset data
CHARGER_MW = 0.05      # 50 kW per charger
POWER_FACTOR = 0.99
EV_BUSES = [18, 25, 32]
SCENARIOS = [0, 1, 5, 10, 20]

def run_scenario(chargers):
    net = pn.case33bw()

    # Apply explicit demonstration ratings to in-service lines.
    net.line.loc[net.line.in_service, "max_i_ka"] = RATING_KA

    # Distribute EV chargers across three buses.
    q_per_charger = CHARGER_MW * math.tan(math.acos(POWER_FACTOR))
    for n in range(chargers):
        bus = EV_BUSES[n % len(EV_BUSES)]
        pp.create_load(
            net,
            bus=bus,
            p_mw=CHARGER_MW,
            q_mvar=q_per_charger,
            name=f"EV charger {n + 1} (50 kW)"
        )

    pp.runpp(net, algorithm="nr", max_iteration=100)

    active = net.line.index[net.line.in_service.astype(bool)]
    rows = []
    for idx in active:
        current = max(
            float(net.res_line.at[idx, "i_from_ka"]),
            float(net.res_line.at[idx, "i_to_ka"])
        )
        loading = current / RATING_KA * 100
        rows.append({
            "chargers_added": chargers,
            "line_id": int(idx),
            "current_ka": current,
            "assumed_rating_ka": RATING_KA,
            "loading_percent": loading,
            "status": "OVERLOAD" if loading > 100 else "HIGH LOADING" if loading >= 80 else "PASS"
        })

    details = pd.DataFrame(rows)
    min_voltage = float(net.res_bus.vm_pu.min())
    summary = {
        "chargers_added": chargers,
        "added_ev_load_kw": chargers * CHARGER_MW * 1000,
        "power_flow_converged": bool(net.converged),
        "lines_assessed": len(details),
        "max_line_loading_percent": float(details.loading_percent.max()),
        "overloaded_lines": int((details.loading_percent > 100).sum()),
        "lines_at_or_above_80_percent": int((details.loading_percent >= 80).sum()),
        "minimum_bus_voltage_pu": min_voltage,
        "voltage_below_0_95_pu": int((net.res_bus.vm_pu < 0.95).sum()),
        "rating_basis": "DEMO ASSUMPTION: 0.25 kA per line"
    }
    return summary, details

def main():
    summaries = []
    all_details = []

    print("=" * 72)
    print("GRIDGUARD — EV CHARGING THERMAL STRESS TEST")
    print("Benchmark: pandapower case33bw | 50 kW per added charger")
    print(f"Line rating assumption: {RATING_KA} kA (NOT verified asset data)")
    print("=" * 72)

    for count in SCENARIOS:
        try:
            summary, details = run_scenario(count)
            summaries.append(summary)
            all_details.append(details)
            print(
                f"{count:>2} chargers | "
                f"EV load {summary['added_ev_load_kw']:>4.0f} kW | "
                f"max loading {summary['max_line_loading_percent']:>7.2f}% | "
                f"overloaded lines {summary['overloaded_lines']:>2} | "
                f"voltage <0.95 pu {summary['voltage_below_0_95_pu']:>2}"
            )
        except Exception as exc:
            print(f"{count:>2} chargers | SCENARIO FAILED: {exc}")
            summaries.append({
                "chargers_added": count,
                "added_ev_load_kw": count * CHARGER_MW * 1000,
                "power_flow_converged": False,
                "error": str(exc),
                "rating_basis": "DEMO ASSUMPTION: 0.25 kA per line"
            })

    summary_path = OUT / "ev_thermal_stress_summary.csv"
    details_path = OUT / "ev_thermal_stress_line_details.csv"
    pd.DataFrame(summaries).to_csv(summary_path, index=False)
    if all_details:
        pd.concat(all_details, ignore_index=True).to_csv(details_path, index=False)

    print("\nReports saved:")
    print(summary_path)
    print(details_path)
    print("\nInterpretation: this is a benchmark simulation, not a real-grid safety certification.")

if __name__ == "__main__":
    main()
