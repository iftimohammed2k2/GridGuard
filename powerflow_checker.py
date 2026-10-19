import json
import argparse
from pathlib import Path

import numpy as np

from gridguard_net_builder import (
    build_network, run_robust_powerflow, add_common_args, units_from_args,
)

BASE_DIR = Path(__file__).resolve().parent
SUMMARY_FILE = BASE_DIR / "baseline_summary.json"
BUS_RESULTS = BASE_DIR / "baseline_bus_results.csv"


def compute_fvsi(net):
    """Fast Voltage Stability Index per in-service line.

    FVSI = 4 Z^2 Qr / (Vs^2 X), with Z and X in ohms, Vs in kV and Qr in MVAr.
    Vs and Qr follow the actual flow direction, not the CSV's from/to order.
    """
    out = []
    for idx, line in net.line.iterrows():
        if not line.in_service:
            continue
        res = net.res_line.loc[idx]
        if res.p_from_mw >= 0:
            sending, q_recv = int(line.from_bus), -float(res.q_to_mvar)
        else:
            sending, q_recv = int(line.to_bus), -float(res.q_from_mvar)
        q_recv = max(0.0, q_recv)
        v_kv = float(net.res_bus.at[sending, "vm_pu"]) * float(net.bus.at[sending, "vn_kv"])
        r_total = float(line.r_ohm_per_km) * float(line.length_km)
        x_total = float(line.x_ohm_per_km) * float(line.length_km)
        if x_total <= 0 or v_kv <= 0 or not np.isfinite(v_kv):
            continue
        fvsi = 4.0 * (r_total ** 2 + x_total ** 2) * q_recv / (v_kv ** 2 * x_total)
        out.append({
            "line": line["name"],
            "fvsi": round(float(fvsi), 4),
            "status": "STABLE" if fvsi <= 1.0 else "UNSTABLE",
        })
    return out


def main():
    parser = argparse.ArgumentParser()
    add_common_args(parser)
    args = parser.parse_args()

    net = build_network(args.buses_csv, args.lines_csv, units_from_args(args))

    if not run_robust_powerflow(net):
        SUMMARY_FILE.write_text(json.dumps({
            "converged": False,
            "error": net.get("gg_pf_error", "power flow did not converge"),
            "metrics": {"min_voltage_pu": "N/A", "total_network_loss_mw": "N/A",
                        "reactive_loss_pct": "N/A"},
            "fvsi_analysis": [],
        }, indent=2))
        BUS_RESULTS.write_text("")  # keeps the output set complete so the dashboard can explain
        print("Power flow did not converge with any solver.")
        return

    net.res_bus.to_csv(BUS_RESULTS)

    total_loss = float(net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum())
    total_gen = float(net.res_ext_grid.p_mw.sum())
    loss_pct = (total_loss / total_gen) * 100 if total_gen > 0 else 0.0

    # Share of the source's reactive output that is consumed by the network itself
    q_gen = float(net.res_ext_grid.q_mvar.sum())
    q_load = float(net.load.q_mvar.sum())
    q_loss_pct = ((q_gen - q_load) / q_gen) * 100 if q_gen > 0 else 0.0

    fvsi_data, fvsi_error = [], ""
    try:
        fvsi_data = compute_fvsi(net)
    except Exception as e:  # noqa: BLE001
        fvsi_error = str(e)

    vm = net.res_bus.vm_pu
    summary = {
        "converged": True,
        "solver": net.get("gg_pf_algorithm", ""),
        "metrics": {
            "min_voltage_pu": round(float(vm.min()), 4),
            "min_voltage_bus": str(net.bus.at[vm.idxmin(), "name"]),
            "max_voltage_pu": round(float(vm.max()), 4),
            "total_network_loss_mw": round(total_loss, 4),
            "loss_percentage": round(loss_pct, 2),
            "reactive_loss_pct": round(q_loss_pct, 2),
        },
        "fvsi_analysis": fvsi_data,
    }
    if fvsi_error:
        summary["fvsi_error"] = fvsi_error
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2))
    print(f"Power flow complete. Min voltage: {summary['metrics']['min_voltage_pu']}")


if __name__ == "__main__":
    main()