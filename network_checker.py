def check_network_data(buses, lines):
    errors = []
    bus_ids = [bus["id"] for bus in buses]

    # 1. Check for duplicate bus IDs
    if len(bus_ids) != len(set(bus_ids)):
        errors.append("Duplicate bus IDs found.")

    # 2. Build the network connections
    connections = {bus_id: [] for bus_id in set(bus_ids)}

    for line in lines:
        if line["from"] not in bus_ids:
            errors.append(
                f"Line {line['id']} has a missing starting bus."
            )
            continue

        if line["to"] not in bus_ids:
            errors.append(
                f"Line {line['id']} has a missing ending bus."
            )
            continue

        if line["length_km"] <= 0:
            errors.append(
                f"Line {line['id']} has an invalid length."
            )

        connections[line["from"]].append(line["to"])
        connections[line["to"]].append(line["from"])

    print("\n===== GRIDGUARD VALIDATION REPORT =====")

    if errors:
        print("\nERRORS:")
        for error in errors:
            print("-", error)
    else:
        print("\nNo data errors found.")

    # 3. Check network connectivity
    if bus_ids and not errors:
        visited = set()
        stack = [bus_ids[0]]

        while stack:
            current_bus = stack.pop()

            if current_bus in visited:
                continue

            visited.add(current_bus)

            for neighbour in connections[current_bus]:
                if neighbour not in visited:
                    stack.append(neighbour)

        disconnected = set(bus_ids) - visited

        print("\nCONNECTIVITY CHECK:")

        if disconnected:
            print("WARNING: Disconnected buses found:")
            for bus_id in sorted(disconnected):
                print("-", bus_id)
        else:
            print("All buses are connected.")

    elif errors:
        print("\nConnectivity check skipped due to data errors.")

    print("\nTotal errors:", len(errors))
    print("Validation complete.")


# Sample network: bus 4 is intentionally disconnected
buses = [
    {"id": 1},
    {"id": 2},
    {"id": 3},
    {"id": 4}
]

lines = [
    {"id": "L1", "from": 1, "to": 2, "length_km": 1.5},
    {"id": "L2", "from": 2, "to": 3, "length_km": 0.8}
]

check_network_data(buses, lines)