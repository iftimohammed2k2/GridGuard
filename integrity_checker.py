import json
import argparse
from pathlib import Path

import networkx as nx

from gridguard_net_builder import build_network, add_common_args, units_from_args

BASE_DIR = Path(__file__).resolve().parent
SUMMARY_FILE = BASE_DIR / "integrity_summary.json"


def main():
    parser = argparse.ArgumentParser()
    add_common_args(parser)
    args = parser.parse_args()

    try:
        net = build_network(args.buses_csv, args.lines_csv, units_from_args(args))
    except Exception as e:  # noqa: BLE001
        SUMMARY_FILE.write_text(json.dumps({"status": "FAIL", "errors": [str(e)]}, indent=2))
        print(f"Integrity check failed: {e}")
        return

    name = net.bus["name"]
    slack = int(net.ext_grid.bus.iloc[0])

    # Graph of everything that is switched in (open tie lines are left out)
    G = nx.MultiGraph()
    G.add_nodes_from(net.bus.index)
    for _, row in net.line[net.line.in_service].iterrows():
        G.add_edge(int(row.from_bus), int(row.to_bus))
    for _, row in net.trafo[net.trafo.in_service].iterrows():
        G.add_edge(int(row.hv_bus), int(row.lv_bus))

    components = nx.number_connected_components(G)
    is_radial = G.number_of_edges() == G.number_of_nodes() - components
    supplied = nx.node_connected_component(G, slack)
    unsupplied = [b for b in net.bus.index if b not in supplied]
    unsupplied_load = float(net.load[net.load.bus.isin(unsupplied)].p_mw.sum()) if unsupplied else 0.0
    total_load = float(net.load.p_mw.sum()) if len(net.load) else 0.0

    warnings = []
    if components > 1:
        warnings.append(f"The network splits into {components} separate islands.")
    if unsupplied:
        shown = ", ".join(str(name[b]) for b in unsupplied[:10])
        more = f" and {len(unsupplied) - 10} more" if len(unsupplied) > 10 else ""
        warnings.append(f"{len(unsupplied)} bus(es) cannot be reached from the source "
                        f"({unsupplied_load:.3f} MW of load): {shown}{more}.")
    if total_load <= 0.0011:
        warnings.append("Total load is almost zero. Check the load column and its units.")

    # Topology for the dashboard map (includes open tie lines)
    edges = []
    for _, row in net.line.iterrows():
        edges.append({"from": str(name[int(row.from_bus)]), "to": str(name[int(row.to_bus)]),
                      "in_service": bool(row.in_service)})
    for _, row in net.trafo.iterrows():
        edges.append({"from": str(name[int(row.hv_bus)]), "to": str(name[int(row.lv_bus)]),
                      "in_service": bool(row.in_service)})

    open_branches = int((~net.line.in_service).sum()) + int((~net.trafo.in_service).sum())
    status = "PASS" if components == 1 else "REVIEW"

    summary = {
        "status": status,
        "metrics": {
            "bus_count": int(len(net.bus)),
            "line_count": int(len(net.line) + len(net.trafo)),
            "open_branches": open_branches,
            "total_load_mw": round(total_load, 3),
            "is_radial": bool(is_radial),
            "components": int(components),
            "unsupplied_bus_count": len(unsupplied),
            "unsupplied_load_mw": round(unsupplied_load, 3),
        },
        "warnings": warnings,
        "report": list(net["gg_report"]),
        "topology": {
            "nodes": [str(n) for n in name.tolist()],
            "edges": edges,
            "slack": str(name[slack]),
        },
    }
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2))
    print(f"Integrity check complete. Islands: {components}, status: {status}")


if __name__ == "__main__":
    main()