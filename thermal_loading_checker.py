import json
import argparse
from pathlib import Path

import numpy as np

from gridguard_net_builder import (
    build_network, run_robust_powerflow, add_common_args, units_from_args,
)

BASE_DIR = Path(__file__).resolve().parent
SUMMARY_FILE = BASE_DIR / "thermal_summary.json"


def get_dynamic_rating(base_rating_ka, ambient_temp_c, wind_speed_m_s=1.0):
    """Simplified ambient/wind derating (not a full IEEE 738 heat balance).

    The static rating is assumed to hold at 25 C ambient and 80 C conductor
    temperature. Wind adds an empirical 5% per m/s.
    """
    t_max = 80.0
    t_rated_amb = 25.0
    if ambient_temp_c >= t_max:
        return 0.0
    factor = np.sqrt((t_max - ambient_temp_c) / (t_max - t_rated_amb))
    wind_factor = 1.0 + 0.05 * wind_speed_m_s
    return base_rating_ka * factor * wind_factor


def main():
    parser = argparse.ArgumentParser()
    add_common_args(parser)
    args = parser.parse_args()

    ambient_temp = 35.0
    wind_speed = 0.61

    net = build_network(args.buses_csv, args.lines_csv, units_from_args(args))

    if not run_robust_powerflow(net):
        SUMMARY_FILE.write_text(json.dumps({
            "status": "FAIL", "overloads": 0, "equipment": [],
            "error": net.get("gg_pf_error", ""),
        }, indent=2))
        return

    equipment = []
    overloads = 0

    for idx in net.line.index[net.line.in_service]:
        current = float(net.res_line.at[idx, "i_ka"])
        if not np.isfinite(current):
            continue
        base_rating = float(net.line.at[idx, "max_i_ka"])
        dynamic_rating = float(get_dynamic_rating(base_rating, ambient_temp, wind_speed))
        loading = (current / dynamic_rating) * 100 if dynamic_rating > 0 else 999.0

        status = "OVERLOAD" if loading > 100 else "PASS"
        if status == "OVERLOAD":
            overloads += 1

        equipment.append({
            "id": net.line.at[idx, "name"],
            "base_rating_ka": round(base_rating, 3),
            "dynamic_rating_ka": round(dynamic_rating, 3),
            "current_ka": round(current, 3),
            "loading_pct": round(loading, 2),
            "status": status,
        })

    summary = {
        "status": "REVIEW" if overloads else "PASS",
        "overloads": overloads,
        "ambient_temp_c": ambient_temp,
        "wind_speed_m_s": wind_speed,
        "equipment": equipment,
    }
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2))
    print(f"Thermal check complete. Overloads: {overloads}")


if __name__ == "__main__":
    main()