import csv
import math
import sys
from collections import defaultdict, deque
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
BUSES_FILE = BASE_DIR / "buses.csv"
LINES_FILE = BASE_DIR / "lines.csv"
REPORT_FILE = BASE_DIR / "integrity_report.txt"

BUS_COLUMNS = ("id", "nominal_kv")
LINE_COLUMNS = (
    "id", "from_bus", "to_bus",
    "length_km", "r_ohm_per_km", "x_ohm_per_km",
)


def read_table(path, required_columns, errors, warnings):
    """Read CSV with strict parsing, unique headers and consistent row widths."""
    path = Path(path)

    if not path.is_file():
        errors.append(f"{path.name}: file does not exist.")
        return []

    try:
        with path.open("r", newline="", encoding="utf-8-sig") as file:
            reader = csv.reader(file, strict=True)

            try:
                raw_header = next(reader)
            except StopIteration:
                errors.append(f"{path.name}: file is empty.")
                return []

            header = [value.strip() for value in raw_header]

            if not any(header):
                errors.append(f"{path.name}: header is empty.")
                return []

            if any(not name for name in header):
                errors.append(f"{path.name}: blank column name detected.")

            duplicates = sorted({
                name for name in header if header.count(name) > 1
            })
            if duplicates:
                errors.append(
                    f"{path.name}: duplicate column names: "
                    + ", ".join(duplicates)
                )
                return []

            missing = sorted(set(required_columns) - set(header))
            if missing:
                errors.append(
                    f"{path.name}: missing required columns: "
                    + ", ".join(missing)
                )
                return []

            extra = sorted(set(header) - set(required_columns))
            if extra:
                warnings.append(
                    f"{path.name}: extra columns ignored: "
                    + ", ".join(extra)
                )

            rows = []
            for values in reader:
                row_number = reader.line_num

                if not values or all(not value.strip() for value in values):
                    continue

                if len(values) != len(header):
                    errors.append(
                        f"{path.name}, line {row_number}: expected "
                        f"{len(header)} fields, received {len(values)}."
                    )
                    continue

                rows.append((
                    row_number,
                    dict(zip(header, [value.strip() for value in values]))
                ))

            if not rows:
                errors.append(f"{path.name}: no usable data rows.")

            return rows

    except (OSError, UnicodeError, csv.Error) as exc:
        errors.append(f"{path.name}: CSV read/parse failure: {exc}")
        return []


def number(value, filename, row, field, errors):
    if value is None or not value.strip():
        errors.append(f"{filename}, line {row}: '{field}' is missing.")
        return None

    try:
        result = float(value)
    except (ValueError, TypeError):
        errors.append(
            f"{filename}, line {row}: '{field}' must be numeric; "
            f"received {value!r}."
        )
        return None

    if not math.isfinite(result):
        errors.append(
            f"{filename}, line {row}: '{field}' must be finite."
        )
        return None

    return result


def validate_network(buses_path, lines_path):
    errors = []
    warnings = []
    info = []

    bus_rows = read_table(
        buses_path, BUS_COLUMNS, errors, warnings
    )
    line_rows = read_table(
        lines_path, LINE_COLUMNS, errors, warnings
    )

    bus_ids = set()

    for row_number, row in bus_rows:
        bus_id = row["id"]

        if not bus_id:
            errors.append(
                f"buses.csv, line {row_number}: bus ID is missing."
            )
        elif bus_id in bus_ids:
            errors.append(
                f"buses.csv, line {row_number}: duplicate bus ID {bus_id!r}."
            )
        else:
            bus_ids.add(bus_id)

        voltage = number(
            row["nominal_kv"], "buses.csv", row_number,
            "nominal_kv", errors
        )
        if voltage is not None and voltage <= 0:
            errors.append(
                f"buses.csv, line {row_number}: nominal_kv must be > 0."
            )

    line_ids = set()
    graph = defaultdict(set)
    valid_connections = 0

    for row_number, row in line_rows:
        line_id = row["id"]
        source = row["from_bus"]
        target = row["to_bus"]

        if not line_id:
            errors.append(
                f"lines.csv, line {row_number}: line ID is missing."
            )
        elif line_id in line_ids:
            errors.append(
                f"lines.csv, line {row_number}: duplicate line ID {line_id!r}."
            )
        else:
            line_ids.add(line_id)

        source_ok = bool(source) and source in bus_ids
        target_ok = bool(target) and target in bus_ids

        if not source:
            errors.append(
                f"lines.csv, line {row_number}: from_bus is missing."
            )
        elif not source_ok:
            errors.append(
                f"lines.csv, line {row_number}: from_bus {source!r} "
                "does not exist."
            )

        if not target:
            errors.append(
                f"lines.csv, line {row_number}: to_bus is missing."
            )
        elif not target_ok:
            errors.append(
                f"lines.csv, line {row_number}: to_bus {target!r} "
                "does not exist."
            )

        if source and target and source == target:
            errors.append(
                f"lines.csv, line {row_number}: self-loop detected "
                f"at bus {source!r}."
            )

        length = number(
            row["length_km"], "lines.csv", row_number,
            "length_km", errors
        )
        resistance = number(
            row["r_ohm_per_km"], "lines.csv", row_number,
            "r_ohm_per_km", errors
        )
        reactance = number(
            row["x_ohm_per_km"], "lines.csv", row_number,
            "x_ohm_per_km", errors
        )

        if length is not None and length <= 0:
            errors.append(
                f"lines.csv, line {row_number}: length_km must be > 0."
            )

        if resistance is not None and resistance < 0:
            errors.append(
                f"lines.csv, line {row_number}: resistance cannot be negative."
            )

        if reactance is not None and reactance < 0:
            errors.append(
                f"lines.csv, line {row_number}: reactance cannot be negative."
            )

        if resistance == 0 and reactance == 0:
            warnings.append(
                f"lines.csv, line {row_number}: both R and X are zero; "
                "verify the model."
            )

        # Connectivity is a topology check, separate from electrical validity.
        if source_ok and target_ok and source != target:
            graph[source].add(target)
            graph[target].add(source)
            valid_connections += 1

    if bus_ids:
        visited = set()
        components = []

        for start in sorted(bus_ids):
            if start in visited:
                continue

            component = []
            queue = deque([start])
            visited.add(start)

            while queue:
                current = queue.popleft()
                component.append(current)

                for neighbor in graph[current]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)

            components.append(component)

        isolated = sorted(bus for bus in bus_ids if not graph[bus])
        if isolated:
            warnings.append(
                "Buses without valid line connections: "
                + ", ".join(isolated)
            )

        if len(components) > 1:
            descriptions = [
                "{" + ", ".join(sorted(component)) + "}"
                for component in components
            ]
            warnings.append(
                f"Network has {len(components)} disconnected components: "
                + "; ".join(descriptions)
            )
        else:
            info.append("All listed buses belong to one connected component.")

    status = "FAIL" if errors else "REVIEW" if warnings else "PASS"

    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "info": info,
        "bus_count": len(bus_rows),
        "line_count": len(line_rows),
        "valid_connections": valid_connections,
    }


def format_report(result):
    lines = [
        "=" * 64,
        "GRIDGUARD — NETWORK DATA INTEGRITY REPORT",
        "=" * 64,
        f"Buses read: {result['bus_count']}",
        f"Lines read: {result['line_count']}",
        f"Valid bus connections: {result['valid_connections']}",
        f"Errors: {len(result['errors'])}",
        f"Warnings: {len(result['warnings'])}",
        "",
    ]

    for label, key in (
        ("INFORMATION", "info"),
        ("WARNINGS", "warnings"),
        ("ERRORS", "errors"),
    ):
        if result[key]:
            lines.append(label)
            lines.extend(f"  - {message}" for message in result[key])
            lines.append("")

    lines += [
        "-" * 64,
        f"INTEGRITY RESULT: {result['status']}",
        "Scope: CSV schema, values, identifiers, references and connectivity.",
        "This check does not certify power-flow convergence or electrical safety.",
        "=" * 64,
    ]
    return "\n".join(lines)


def main():
    result = validate_network(BUSES_FILE, LINES_FILE)
    report = format_report(result)
    print(report)

    try:
        REPORT_FILE.write_text(report + "\n", encoding="utf-8")
        print(f"\nReport saved to: {REPORT_FILE}")
    except OSError as exc:
        print(f"Could not save report: {exc}", file=sys.stderr)
        return 2

    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())