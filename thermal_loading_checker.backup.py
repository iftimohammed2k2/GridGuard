import json
import math
from pathlib import Path

import pandapower as pp
import pandapower.networks as pn


BASE_DIR = Path(__file__).resolve().parent
REPORT_FILE = BASE_DIR / "thermal_report.txt"
SUMMARY_FILE = BASE_DIR / "thermal_summary.json"
RESULTS_FILE = BASE_DIR / "thermal_results.csv"

MAX_LOADING_PERCENT = 100.0


def finite_positive(value):
    try:
        value = float(value)
        return math.isfinite(value) and value > 0
    except (TypeError, ValueError):
        return False


def classify_loading(loading_percent, rating_valid,
                     threshold=MAX_LOADING_PERCENT):
    """Classify loading without treating missing ratings as zero loading."""
    if not rating_valid:
        return "NOT ASSESSABLE"

    try:
        loading = float(loading_percent)
    except (TypeError, ValueError):
        return "NOT ASSESSABLE"

    if not math.isfinite(loading) or loading < 0:
        return "NOT ASSESSABLE"

    if loading > threshold:
        return "OVERLOAD"

    return "PASS"


def assess_equipment(net, result_table, element_type, threshold):
    equipment = getattr(net, element_type)
    rows = []

    if equipment.empty:
        return rows

    for equipment_id, item in equipment.iterrows():
        if not bool(item.get("in_service", True)):
            continue

        record = {
            "equipment_type": element_type,
            "equipment_id": str(equipment_id),
            "loading_percent": None,
            "rating_valid": False,
            "status": "NOT ASSESSABLE",
            "rating_note": "",
        }

        if equipment_id not in result_table.index:
            record["rating_note"] = "No calculated result for this element."
            rows.append(record)
            continue

        result = result_table.loc[equipment_id]

        if element_type == "line":
            max_current = item.get("max_i_ka")
            derating = item.get("df", 1.0)
            parallel = item.get("parallel", 1)

            rating_valid = (
                finite_positive(max_current)
                and finite_positive(derating)
                and finite_positive(parallel)
                and float(derating) <= 1.0
                and float(parallel).is_integer()
            )

            if rating_valid:
                effective_rating = (
                    float(max_current) * float(derating) * int(parallel)
                )
                record["rating_note"] = (
                    f"Effective current rating: {effective_rating:.6f} kA"
                )
            else:
                record["rating_note"] = (
                    "Missing or invalid max_i_ka, df, or parallel rating."
                )

        elif element_type == "trafo":
            rating = item.get("sn_mva")
            derating = item.get("df", 1.0)
            parallel = item.get("parallel", 1)

            rating_valid = (
                finite_positive(max_current) 
                and float(max_current) < 1000.0
                and finite_positive(derating)
                and finite_positive(parallel)
                and float(derating) <= 1.0
                and float(parallel).is_integer()
            )

            if rating_valid:
                record["rating_note"] = (
                    f"Rated power: {float(rating):.6f} MVA; "
                    f"derating factor: {float(derating):.3f}; "
                    f"parallel units: {int(parallel)}"
                )
            else:
                record["rating_note"] = (
                    "Missing or invalid sn_mva, df, or parallel rating."
                )

        loading = result.get("loading_percent")
        record["rating_valid"] = bool(rating_valid)

        if loading is not None:
            try:
                value = float(loading)
                if math.isfinite(value):
                    record["loading_percent"] = value
            except (TypeError, ValueError):
                pass

        record["status"] = classify_loading(
            record["loading_percent"], rating_valid, threshold
        )

        if record["status"] == "NOT ASSESSABLE":
            if not record["rating_note"]:
                record["rating_note"] = (
                    "Valid loading result or rating unavailable."
                )

        rows.append(record)

    return rows


def run_thermal_check(net, threshold=MAX_LOADING_PERCENT):
    errors = []

    try:
        pp.runpp(
            net,
            algorithm="nr",
            numba=False,
            init="auto",
            max_iteration=30,
        )
    except Exception as exc:
        return {
            "status": "FAIL",
            "converged": False,
            "errors": [
                f"Power flow failed: {type(exc).__name__}: {exc}"
            ],
            "equipment": [],
        }

    if not net.converged:
        return {
            "status": "FAIL",
            "converged": False,
            "errors": ["Power flow did not converge."],
            "equipment": [],
        }

    equipment = []
    equipment.extend(
        assess_equipment(net, net.res_line, "line", threshold)
    )
    equipment.extend(
        assess_equipment(net, net.res_trafo, "trafo", threshold)
    )

    overloads = [
        row for row in equipment if row["status"] == "OVERLOAD"
    ]
    unassessable = [
        row for row in equipment
        if row["status"] == "NOT ASSESSABLE"
    ]

    if overloads:
        status = "REVIEW"
    elif unassessable:
        status = "INCOMPLETE"
    else:
        status = "PASS"

    return {
        "status": status,
        "converged": True,
        "errors": errors,
        "equipment": equipment,
        "threshold_percent": threshold,
        "overload_count": len(overloads),
        "unassessable_count": len(unassessable),
        "assessed_count": len(equipment) - len(unassessable),
        "line_count": sum(
            row["equipment_type"] == "line" for row in equipment
        ),
        "transformer_count": sum(
            row["equipment_type"] == "trafo" for row in equipment
        ),
    }


def save_report(result):
    lines = [
        "=" * 66,
        "GRIDGUARD — THERMAL LOADING REPORT",
        "=" * 66,
        f"Power flow converged: {result['converged']}",
    ]

    if not result["converged"]:
        lines.extend(f"ERROR: {e}" for e in result["errors"])
    else:
        lines.extend([
            f"Loading threshold: {result['threshold_percent']:.1f}%",
            f"Lines considered: {result['line_count']}",
            f"Transformers considered: {result['transformer_count']}",
            f"Equipment assessed: {result['assessed_count']}",
            f"Overloads detected: {result['overload_count']}",
            f"Equipment not assessable: {result['unassessable_count']}",
            "",
            "EQUIPMENT DETAILS",
        ])

        for row in result["equipment"]:
            loading = row["loading_percent"]
            loading_text = (
                f"{loading:.2f}%" if loading is not None else "N/A"
            )
            lines.append(
                f"{row['equipment_type']} {row['equipment_id']}: "
                f"{row['status']} | Loading: {loading_text} | "
                f"{row['rating_note']}"
            )

    lines.extend([
        "",
        f"THERMAL SCREENING RESULT: {result['status']}",
        "Ratings must be supported by equipment data or manufacturer records.",
        "This screening is not a thermal study or safety certification.",
        "=" * 66,
    ])

    report = "\n".join(lines)
    REPORT_FILE.write_text(report + "\n", encoding="utf-8")

    if result["converged"]:
        with RESULTS_FILE.open("w", newline="", encoding="utf-8") as file:
            import csv
            fields = [
                "equipment_type", "equipment_id", "loading_percent",
                "rating_valid", "status", "rating_note",
            ]
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(result["equipment"])

        SUMMARY_FILE.write_text(
            json.dumps(
                {k: v for k, v in result.items() if k != "equipment"},
                indent=2,
            ),
            encoding="utf-8",
        )

    return report


def main():
    # Start with the same benchmark used by the baseline checker.
    net = pn.case33bw()
    result = run_thermal_check(net)
    print(save_report(result))
    print(f"\nReport: {REPORT_FILE}")

    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())