import csv
import random

def save_grid(name, buses, lines):
    with open(f"{name}_buses.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "nominal_kv", "is_slack", "load_p_mw", "load_q_mvar"])
        writer.writerows(buses)
    with open(f"{name}_lines.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "from_bus", "to_bus", "length_km", "r_ohm_per_km", "x_ohm_per_km", "max_i_ka"])
        writer.writerows(lines)
    print(f"✅ Generated {name}_buses.csv and {name}_lines.csv")

# ==========================================
# 1. BANGLADESH (11kV / 0.4kV, 50Hz, Dense Load)
# Typical urban distribution (e.g., Dhaka)
# ==========================================
bd_buses = [
    ["BD1", 11, True, 0, 0],
    ["BD2", 11, False, 2.5, 1.2],
    ["BD3", 11, False, 3.0, 1.5],
    ["BD4", 0.4, False, 1.5, 0.8] # Step-down to 400V for a neighborhood
]
bd_lines = [
    ["BDL1", "BD1", "BD2", 1.2, 0.15, 0.08, 0.4],
    ["BDL2", "BD2", "BD3", 0.8, 0.18, 0.09, 0.4],
    ["BDT1", "BD3", "BD4", 0.0, 0.0, 0.0, 1.0] # Transformer
]
save_grid("bangladesh", bd_buses, bd_lines)

# ==========================================
# 2. NORWAY (22kV / 0.4kV, 50Hz, Long Distances, Hydro)
# Sparse population, very long cables, high voltage
# ==========================================
no_buses = [
    ["NO1", 22, True, 0, 0],
    ["NO2", 22, False, 0.8, 0.2],
    ["NO3", 22, False, 0.5, 0.1],
    ["NO4", 0.4, False, 0.2, 0.05]
]
no_lines = [
    ["NOL1", "NO1", "NO2", 15.0, 0.12, 0.15, 0.2], # 15km long line
    ["NOL2", "NO2", "NO3", 25.0, 0.12, 0.15, 0.2], # 25km long line
    ["NOT1", "NO3", "NO4", 0.0, 0.0, 0.0, 1.0]
]
save_grid("norway", no_buses, no_lines)

# ==========================================
# 3. JAPAN (6.6kV / 0.2kV, 50/60Hz, Underground)
# Compact, heavy load, underground cables
# ==========================================
jp_buses = [
    ["JP1", 6.6, True, 0, 0],
    ["JP2", 6.6, False, 1.8, 0.6],
    ["JP3", 6.6, False, 2.2, 0.8],
    ["JP4", 0.2, False, 0.9, 0.3] # 200V standard
]
jp_lines = [
    ["JPL1", "JP1", "JP2", 0.5, 0.08, 0.06, 0.6],
    ["JPL2", "JP2", "JP3", 0.3, 0.08, 0.06, 0.6],
    ["JPT1", "JP3", "JP4", 0.0, 0.0, 0.0, 1.0]
]
save_grid("japan", jp_buses, jp_lines)

# ==========================================
# 4. USA (12.47kV / 0.24kV, 60Hz, Standard)
# Classic American overhead feeder
# ==========================================
us_buses = [
    ["US1", 12.47, True, 0, 0],
    ["US2", 12.47, False, 4.0, 1.5],
    ["US3", 12.47, False, 3.5, 1.2],
    ["US4", 12.47, False, 2.0, 0.8],
    ["US5", 0.24, False, 1.0, 0.4]
]
us_lines = [
    ["USL1", "US1", "US2", 2.0, 0.2, 0.1, 0.5],
    ["USL2", "US2", "US3", 1.5, 0.2, 0.1, 0.5],
    ["USL3", "US3", "US4", 1.0, 0.2, 0.1, 0.5],
    ["UST1", "US4", "US5", 0.0, 0.0, 0.0, 1.0]
]
save_grid("usa", us_buses, us_lines)

# ==========================================
# 5. AUSTRALIA (11kV / 0.4kV, 50Hz, Solar Heavy)
# Long rural feeder with high solar generation
# ==========================================
au_buses = [
    ["AU1", 11, True, 0, 0],
    ["AU2", 11, False, 0.5, 0.1],
    ["AU3", 11, False, 0.4, 0.1],
    ["AU4", 11, False, 0.3, 0.1],
    ["AU5", 0.4, False, 0.2, 0.1]
]
au_lines = [
    ["AUL1", "AU1", "AU2", 5.0, 0.25, 0.2, 0.3],
    ["AUL2", "AU2", "AU3", 8.0, 0.25, 0.2, 0.3],
    ["AUL3", "AU3", "AU4", 6.0, 0.25, 0.2, 0.3],
    ["AUT1", "AU4", "AU5", 0.0, 0.0, 0.0, 1.0]
]
save_grid("australia", au_buses, au_lines)

# ==========================================
# 6. MIDDLE EAST (33kV / 11kV / 0.4kV, 50Hz)
# Massive industrial loads, cascading transformers
# ==========================================
me_buses = [
    ["ME1", 33, True, 0, 0],
    ["ME2", 33, False, 8.0, 3.0],
    ["ME3", 11, False, 5.0, 2.0],
    ["ME4", 0.4, False, 2.5, 1.0]
]
me_lines = [
    ["MEL1", "ME1", "ME2", 3.0, 0.1, 0.1, 0.8],
    ["MET1", "ME2", "ME3", 0.0, 0.0, 0.0, 2.0], # 33kV to 11kV Trafo
    ["MET2", "ME3", "ME4", 0.0, 0.0, 0.0, 1.0]  # 11kV to 0.4kV Trafo
]
save_grid("middle_east", me_buses, me_lines)

print("\nAll grids generated! Upload any of these to GridGuard.")
