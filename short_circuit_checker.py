import json
import math
import argparse
from pathlib import Path

import pandapower.shortcircuit as sc

from gridguard_net_builder import build_network, add_common_args, units_from_args

BASE_DIR = Path(__file__).resolve().parent
SUMMARY_FILE = BASE_DIR / "short_circuit_summary.json"


def main():
    parser = argparse.ArgumentParser()
    add_common_args(parser)
    parser.add_argument("--source-mva", type=float, default=100.0,
                        help="Short-circuit level of the upstream source in MVA")
    args = parser.parse_args()

    net = build_network(args.buses_csv, args.lines_csv, units_from_args(args))
    net.ext_grid["s_sc_max_mva"] = args.source_mva

    try:
        sc.calc_sc(net, case="max", fault="3ph")
    except Exception as e:  # noqa: BLE001
        SUMMARY_FILE.write_text(json.dumps({
            "status": "FAIL", "error": str(e),
            "all_buses": [], "max_fault_current_ka": "N/A",
        }, indent=2))
        print(f"Short-circuit calculation failed: {e}")
        return

    results, unreachable = [], []
    for idx, value in net.res_bus_sc.ikss_ka.items():
        bus_name = str(net.bus.at[idx, "name"])
        if value is None or not math.isfinite(float(value)):
            unreachable.append(bus_name)
            continue
        results.append({"bus_id": bus_name, "fault_current_ka": round(float(value), 3)})

    results.sort(key=lambda r: r["fault_current_ka"], reverse=True)

    summary = {
        "status": "PASS" if results else "FAIL",
        "max_fault_current_ka": results[0]["fault_current_ka"] if results else "N/A",
        "critical_bus": results[0]["bus_id"] if results else "N/A",
        "min_fault_current_ka": results[-1]["fault_current_ka"] if results else "N/A",
        "min_bus": results[-1]["bus_id"] if results else "N/A",
        "source_mva": args.source_mva,
        "method": "IEC 60909 maximum 3-phase fault (pandapower), voltage factor c = 1.1",
        "unreachable_buses": unreachable[:20],
        "unreachable_count": len(unreachable),
        "all_buses": results,
    }
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2))
    print(f"Short-circuit complete. Max fault: {summary['max_fault_current_ka']} kA")


if __name__ == "__main__":
    main()