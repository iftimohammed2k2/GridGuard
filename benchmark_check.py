import pandapower.networks as pn
import math

# Load a benchmark distribution network
net = pn.case33bw()

errors = []
warnings = []

bus_ids = set(net.bus.index)

print("\n===== GRIDGUARD BENCHMARK TEST =====")
print("Network: 33-bus Baran-Wu distribution benchmark")
print("Buses:", len(net.bus))
print("Lines:", len(net.line))

# 1. Check bus IDs and nominal voltages
if net.bus.index.has_duplicates:
    errors.append("Duplicate bus IDs found.")

for bus_id, bus in net.bus.iterrows():
    voltage = bus["vn_kv"]

    if not math.isfinite(float(voltage)) or voltage <= 0:
        errors.append(
            f"Bus {bus_id}: invalid nominal voltage."
        )

# 2. Check line endpoints and parameters
for line_id, line in net.line.iterrows():
    start = line["from_bus"]
    end = line["to_bus"]

    if start not in bus_ids:
        errors.append(
            f"Line {line_id}: starting bus does not exist."
        )

    if end not in bus_ids:
        errors.append(
            f"Line {line_id}: ending bus does not exist."
        )

    for field in [
        "length_km",
        "r_ohm_per_km",
        "x_ohm_per_km"
    ]:
        value = line[field]

        if not math.isfinite(float(value)):
            errors.append(
                f"Line {line_id}: {field} is not finite."
            )
        elif field == "length_km" and value <= 0:
            errors.append(
                f"Line {line_id}: length must be positive."
            )
        elif field != "length_km" and value < 0:
            errors.append(
                f"Line {line_id}: {field} is negative."
            )

# 3. Check connectivity using a graph search
graph = {bus_id: set() for bus_id in bus_ids}

for _, line in net.line.iterrows():
    if not bool(line["in_service"]):
        continue

    start = line["from_bus"]
    end = line["to_bus"]

    if start in graph and end in graph:
        graph[start].add(end)
        graph[end].add(start)

if bus_ids:
    visited = set()
    stack = [next(iter(bus_ids))]

    while stack:
        current = stack.pop()

        if current in visited:
            continue

        visited.add(current)
        stack.extend(graph[current] - visited)

    unreachable = bus_ids - visited

    if unreachable:
        warnings.append(
            f"{len(unreachable)} buses are unreachable "
            "from the selected starting bus."
        )

# 4. Report results
print("\nErrors:", len(errors))
print("Warnings:", len(warnings))

for item in errors:
    print("[ERROR]", item)

for item in warnings:
    print("[WARNING]", item)

if errors:
    print("\nRESULT: FAIL")
elif warnings:
    print("\nRESULT: REVIEW")
else:
    print("\nRESULT: PASS - implemented checks found no issues.")