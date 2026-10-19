import csv
import argparse
import networkx as nx
from pathlib import Path

def check_network_data(buses_path, lines_path):
    print("\n" + "="*50)
    print("🛡️ ZENITHIC GRIDGUARD - TOPOLOGY DIAGNOSTIC TOOL")
    print("="*50)
    
    errors = []
    warnings = []

    # 1. Load Data
    try:
        with open(buses_path, 'r', encoding='utf-8-sig') as f:
            buses = list(csv.DictReader(f))
        with open(lines_path, 'r', encoding='utf-8-sig') as f:
            lines = list(csv.DictReader(f))
    except Exception as e:
        print(f"❌ CRITICAL ERROR: Could not read files. {e}")
        return

    if not buses:
        print("❌ CRITICAL ERROR: buses.csv is empty.")
        return

    # 2. Extract Bus IDs and check for duplicates
    bus_ids = [b.get("id", b.get("bus", "")) for b in buses]
    bus_set = set(bus_ids)
    
    if len(bus_ids) != len(bus_set):
        errors.append("Duplicate bus IDs found in buses.csv.")

    # 3. Build the Graph using NetworkX
    G = nx.Graph()
    G.add_nodes_from(bus_set)

    valid_lines = 0
    for line in lines:
        line_id = line.get("id", "Unknown")
        f_bus = line.get("from_bus", line.get("from", ""))
        t_bus = line.get("to_bus", line.get("to", ""))
        length = line.get("length_km", "0")

        if f_bus not in bus_set:
            errors.append(f"Line {line_id} has a missing starting bus ({f_bus}).")
            continue
        if t_bus not in bus_set:
            errors.append(f"Line {line_id} has a missing ending bus ({t_bus}).")
            continue
            
        try:
            if float(length) <= 0:
                warnings.append(f"Line {line_id} has an invalid length ({length} km).")
        except ValueError:
            warnings.append(f"Line {line_id} has a non-numeric length.")

        # Add edge to graph
        G.add_edge(f_bus, t_bus, id=line_id)
        valid_lines += 1

    # 4. Report Data Errors
    print(f"\n📊 Total Buses: {len(bus_set)} | Total Valid Lines: {valid_lines}")
    
    if errors:
        print("\n❌ DATA ERRORS:")
        for error in errors:
            print(f"  - {error}")
    if warnings:
        print("\n⚠️ WARNINGS:")
        for warning in warnings:
            print(f"  - {warning}")

    # 5. Connectivity & Topology Check (The NetworkX way)
    if not errors:
        print("\n🔍 CONNECTIVITY CHECK:")
        
        # Check if it's a tree (fully radial, no loops)
        is_tree = nx.is_tree(G)
        if is_tree:
            print("  ✅ Topology is perfectly Radial (Tree).")
        else:
            print("  ⚠️ Topology contains loops (Mesh). Ensure this is intentional.")

        # Check for disconnected islands
        components = list(nx.connected_components(G))
        if len(components) > 1:
            print(f"  ❌ WARNING: Network has {len(components)} disconnected islands!")
            for i, comp in enumerate(components):
                if len(comp) > 1:
                    print(f"     Island {i+1}: {list(comp)}")
        else:
            print("  ✅ All buses are connected to the main grid.")

        # Find the most critical bus (Betweenness Centrality)
        centrality = nx.betweenness_centrality(G)
        if centrality:
            most_critical = max(centrality, key=centrality.get)
            print(f"\n🏆 MOST CRITICAL BUS (Bottleneck): Bus {most_critical} (Centrality: {centrality[most_critical]:.2f})")
            print("   (If this bus fails, the most amount of the grid will be isolated.)")

    print("\n" + "="*50)
    print("VALIDATION COMPLETE")
    print("="*50 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GridGuard Standalone Topology Checker")
    parser.add_argument("--buses-csv", default="buses.csv", help="Path to buses.csv")
    parser.add_argument("--lines-csv", default="lines.csv", help="Path to lines.csv")
    args = parser.parse_args()

    check_network_data(args.buses_csv, args.lines_csv)