import json
import argparse
from pathlib import Path

import networkx as nx

from gridguard_net_builder import build_network, add_common_args, units_from_args

BASE_DIR = Path(__file__).resolve().parent
SUMMARY_FILE = BASE_DIR / "reliability_summary.json"

# Simplified failure rate (failures per km per year) and repair time (hours)
FAILURE_RATE_PER_KM = 0.1
REPAIR_TIME_HOURS = 4.0


def main():
    parser = argparse.ArgumentParser()
    add_common_args(parser)
    args = parser.parse_args()

    net = build_network(args.buses_csv, args.lines_csv, units_from_args(args))

    # Customers per bus (from the file, or one per load bus)
    customers = {int(b): float(c) for b, c in net.bus["gg_customers"].items() if c > 0}
    total_customers = sum(customers.values())

    # Graph of switched-in branches only. Open tie lines are ignored, so no
    # restoration through ties is credited (conservative).
    G = nx.MultiGraph()
    G.add_nodes_from(net.bus.index)
    in_service_lines = net.line[net.line.in_service]
    for idx, row in in_service_lines.iterrows():
        G.add_edge(int(row.from_bus), int(row.to_bus), key=idx)
    for idx, row in net.trafo[net.trafo.in_service].iterrows():
        G.add_edge(int(row.hv_bus), int(row.lv_bus), key=("t", idx))

    source = int(net.ext_grid.bus.iloc[0])
    supplied = nx.node_connected_component(G, source)

    total_ci = 0.0   # customer interruptions per year
    total_cmi = 0.0  # customer interruption hours per year
    for idx, row in in_service_lines.iterrows():
        u, v = int(row.from_bus), int(row.to_bus)
        failure_rate = float(row.length_km) * FAILURE_RATE_PER_KM

        G.remove_edge(u, v, key=idx)
        still_supplied = nx.node_connected_component(G, source)
        G.add_edge(u, v, key=idx)

        affected = sum(c for b, c in customers.items()
                       if b in supplied and b not in still_supplied)
        total_ci += failure_rate * affected
        total_cmi += failure_rate * affected * REPAIR_TIME_HOURS

    if total_customers > 0:
        saifi = total_ci / total_customers
        saidi = total_cmi / total_customers
    else:
        saifi = saidi = 0.0
    caidi = saidi / saifi if saifi > 0 else 0.0

    summary = {
        "status": "PASS",
        "metrics": {
            "SAIFI": round(saifi, 3),
            "SAIDI": round(saidi, 3),
            "CAIDI": round(caidi, 3),
            "Customers": round(total_customers, 1),
            "Total_Line_Length_km": round(float(in_service_lines.length_km.sum()), 2),
        },
        "assumptions": [
            f"Line failure rate {FAILURE_RATE_PER_KM} per km per year, repair time {REPAIR_TIME_HOURS:g} h",
            "Only line faults are counted; transformers and switches are not modelled",
            "No switching or restoration through open tie lines is credited",
            "Customers come from the customers column, otherwise one per load bus",
        ],
    }
    if total_customers == 0:
        summary["assumptions"].append("No customers found, so all indices are zero")
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2))
    print("Reliability analysis complete.")


if __name__ == "__main__":
    main()