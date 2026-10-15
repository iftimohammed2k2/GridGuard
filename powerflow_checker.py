import json
import math
from pathlib import Path

import pandapower as pp
import pandapower.networks as pn


# ============================================================
# GRIDGUARD — BASELINE AC POWER FLOW
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
REPORT_FILE = BASE_DIR / "baseline_report.txt"
SUMMARY_FILE = BASE_DIR / "baseline_summary.json"
BUS_RESULTS_FILE = BASE_DIR / "baseline_bus_results.csv"
LINE_RESULTS_FILE = BASE_DIR / "baseline_line_results.csv"

MIN_VOLTAGE_PU = 0.95
MAX_VOLTAGE_PU = 1.05
POWER_FLOW_ALGORITHM = "nr"


def validate_model(net):
    """Perform essential pre-simulation checks on a pandapower network."""
    errors = []

    if len(net.bus) == 0:
        errors.append("Network contains no buses.")

    if len(net.ext_grid) == 0 or not net.ext_grid["in_service"].any():
        errors.append("No in-service external grid (slack source) exists.")

    for idx, bus in net.bus.iterrows():
        voltage = bus.get("vn_kv")
        if voltage is None:
            errors.append(f"Bus {idx}: nominal voltage is missing.")
        else:
            try:
                value = float(voltage)
                if not math.isfinite(value) or value <= 0:
                    errors.append(
                        f"Bus {idx}: nominal voltage must be finite and > 0."
                    )
            except (TypeError, ValueError):
                errors.append(f"Bus {idx}: invalid nominal voltage.")

    for table_name in ("line", "trafo", "load", "sgen", "gen", "ext_grid"):
        table = getattr(net, table_name, None)
        if table is None or table.empty:
            continue

        for column in table.columns:
            if column in ("name", "type", "std_type"):
                continue

            if table[column].dtype.kind in "iuf":
                values = table[column].dropna()
                if not all(math.isfinite(float(v)) for v in values):
                    errors.append(
                        f"{table_name}.{column}: non-finite numeric value found."
                    )

    # Check active line bus references.
    for idx, line in net.line.iterrows():
        if not bool(line.get("in_service", True)):
            continue
        if line["from_bus"] not in net.bus.index:
            errors.append(f"Line {idx}: from_bus does not exist.")
        if line["to_bus"] not in net.bus.index:
            errors.append(f"Line {idx}: to_bus does not exist.")
        if line["from_bus"] == line["to_bus"]:
            errors.append(f"Line {idx}: self-loop detected.")

    return errors


def analyze_network(net):
    """
    Run baseline AC power flow and return summary plus result tables.
    This function does not modify the caller's network topology.
    """
    errors = validate_model(net)
    if errors:
        return {
            "converged": False,
            "status": "FAIL",
            "errors": errors,
            "warnings": [],
            "summary": {},
            "bus_results": None,
            "line_results": None,
        }

    try:
        pp.runpp(
            net,
            algorithm=POWER_FLOW_ALGORITHM,
            numba=False,
            init="auto",
            max_iteration=30,
            tolerance_mva=1e-8,
        )
    except Exception as exc:
        return {
            "converged": False,
            "status": "FAIL",
            "errors": [f"Power flow failed: {type(exc).__name__}: {exc}"],
            "warnings": [],
            "summary": {},
            "bus_results": None,
            "line_results": None,
        }

    if not bool(net.converged):
        return {
            "converged": False,
            "status": "FAIL",
            "errors": ["Power flow did not converge."],
            "warnings": [],
            "summary": {},
            "bus_results": None,
            "line_results": None,
        }

    bus_results = net.res_bus.copy()
    bus_results.index.name = "bus_id"

    # Only buses in service and with calculated results are screened.
    if "in_service" in net.bus.columns:
        active_bus_ids = net.bus.index[net.bus["in_service"].astype(bool)]
        bus_results = bus_results.loc[
            bus_results.index.intersection(active_bus_ids)
        ]

    if bus_results.empty or "vm_pu" not in bus_results.columns:
        return {
            "converged": False,
            "status": "FAIL",
            "errors": ["Power flow converged but no usable bus voltage results exist."],
            "warnings": [],
            "summary": {},
            "bus_results": None,
            "line_results": None,
        }

    valid_vm = bus_results["vm_pu"].dropna()
    if valid_vm.empty or not all(math.isfinite(float(v)) for v in valid_vm):
        return {
            "converged": False,
            "status": "FAIL",
            "errors": ["Bus voltage results contain missing or non-finite values."],
            "warnings": [],
            "summary": {},
            "bus_results": None,
            "line_results": None,
        }

    low = bus_results[bus_results["vm_pu"] < MIN_VOLTAGE_PU]
    high = bus_results[bus_results["vm_pu"] > MAX_VOLTAGE_PU]

    min_bus = bus_results["vm_pu"].idxmin()
    max_bus = bus_results["vm_pu"].idxmax()

    line_results = net.res_line.copy()
    line_results.index.name = "line_id"

    active_lines = net.line.index[net.line["in_service"].astype(bool)]
    line_results = line_results.loc[
        line_results.index.intersection(active_lines)
    ]

    warnings = []
    if not low.empty or not high.empty:
        warnings.append("One or more bus voltages exceed configured limits.")

    summary = {
        "benchmark": "pandapower case33bw (Baran-Wu 33-bus feeder)",
        "algorithm": POWER_FLOW_ALGORITHM,
        "converged": True,
        "bus_count": int(len(net.bus)),
        "in_service_bus_count": int(len(bus_results)),
        "line_count": int(len(net.line)),
        "in_service_line_count": int(len(line_results)),
        "voltage_limits_pu": {
            "minimum": MIN_VOLTAGE_PU,
            "maximum": MAX_VOLTAGE_PU,
        },
        "minimum_voltage_pu": float(bus_results["vm_pu"].min()),
        "minimum_voltage_bus": str(min_bus),
        "maximum_voltage_pu": float(bus_results["vm_pu"].max()),
        "maximum_voltage_bus": str(max_bus),
        "low_voltage_bus_count": int(len(low)),
        "low_voltage_buses": [str(i) for i in low.index.tolist()],
        "high_voltage_bus_count": int(len(high)),
        "high_voltage_buses": [str(i) for i in high.index.tolist()],
        "total_active_load_mw": float(net.load.loc[
            net.load["in_service"].astype(bool), "p_mw"
        ].sum()) if len(net.load) else 0.0,
        "total_active_generation_mw": float(
            net.res_ext_grid["p_mw"].sum()
        ) if len(net.res_ext_grid) else 0.0,
        "line_loading_assessed": False,
        "line_loading_note": (
            "Thermal loading is deliberately not assessed in this module. "
            "Credible equipment ratings must be validated separately."
        ),
    }

    status = "REVIEW" if warnings else "PASS"

    return {
        "converged": True,
        "status": status,
        "errors": [],
        "warnings": warnings,
        "summary": summary,
        "bus_results": bus_results,
        "line_results": line_results,
    }


def save_results(result):
    """Save reproducible machine-readable and human-readable outputs."""
    if not result["converged"]:
        report_lines = [
            "=" * 64,
            "GRIDGUARD — BASELINE POWER FLOW REPORT",
            "=" * 64,
            "POWER FLOW: FAILED",
            "",
            *[f"ERROR: {e}" for e in result["errors"]],
            "=" * 64,
        ]
    else:
        s = result["summary"]
        report_lines = [
            "=" * 64,
            "GRIDGUARD — BASELINE POWER FLOW REPORT",
            "=" * 64,
            f"Benchmark: {s['benchmark']}",
            f"Algorithm: {s['algorithm']}",
            "POWER FLOW: CONVERGED",
            f"Buses: {s['bus_count']} total; {s['in_service_bus_count']} in service",
            f"Lines: {s['line_count']} total; {s['in_service_line_count']} in service",
            "",
            "BUS VOLTAGE SCREENING",
            f"Configured limits: {MIN_VOLTAGE_PU:.2f}–{MAX_VOLTAGE_PU:.2f} p.u.",
            f"Minimum voltage: {s['minimum_voltage_pu']:.4f} p.u. (Bus {s['minimum_voltage_bus']})",
            f"Maximum voltage: {s['maximum_voltage_pu']:.4f} p.u. (Bus {s['maximum_voltage_bus']})",
            f"Buses below minimum: {s['low_voltage_bus_count']}",
            f"Low-voltage bus IDs: {s['low_voltage_buses']}",
            f"Buses above maximum: {s['high_voltage_bus_count']}",
            f"High-voltage bus IDs: {s['high_voltage_buses']}",
            "",
            "THERMAL LOADING",
            "NOT ASSESSED — equipment ratings require separate validation.",
            "",
            f"OVERALL BASELINE STATUS: {result['status']}",
            *[f"WARNING: {w}" for w in result["warnings"]],
            "",
            "Scope: baseline AC power flow and configured bus voltage screening.",
            "This report is not a safety certification or hosting-capacity study.",
            "=" * 64,
        ]

        result["bus_results"].to_csv(BUS_RESULTS_FILE)
        result["line_results"].to_csv(LINE_RESULTS_FILE)
        SUMMARY_FILE.write_text(
            json.dumps(s, indent=2), encoding="utf-8"
        )

    REPORT_FILE.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    return "\n".join(report_lines)


def main():
    net = pn.case33bw()
    result = analyze_network(net)
    print(save_results(result))

    if result["converged"]:
        print(f"\nReport saved: {REPORT_FILE}")
        print(f"Summary saved: {SUMMARY_FILE}")
        print(f"Bus results saved: {BUS_RESULTS_FILE}")
        print(f"Line results saved: {LINE_RESULTS_FILE}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())