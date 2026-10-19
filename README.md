# ⚡ Zenithic GridGuard
**Enterprise Power Systems Analysis Platform**

GridGuard is a high-speed, web-based screening tool for electrical distribution grids. Founded by **Ifti Mohammed Muntakim**, an EEE student from Bangladesh, Zenithic builds modern software for power systems engineers.

GridGuard allows engineers to upload raw power grid data (CSVs), instantly run advanced physics simulations, and calculate exactly how many Electric Vehicles (EVs) a neighborhood can support before the grid collapses.

## 🚀 Features
- **Smart Data Ingestion:** Accepts standard IEEE, MATPOWER, OpenDSS, and ETAP CSV formats with auto-detection of units (kW vs MW, miles vs km, per-unit). Handles tie-switches (normally open lines) and dynamic transformer sizing.
- **N-1 Contingency Analysis:** Simulates the failure of every single line to check for grid collapse.
- **IEC 60909 Short-Circuit:** Calculates exact 3-phase fault currents at every bus using native Pandapower per-unit math.
- **Dynamic Thermal Ratings:** Adjusts line limits based on real-time ambient temperature and wind speed.
- **Probabilistic EV Hosting Capacity:** Runs Monte Carlo simulations and a Binary Search algorithm to find the exact maximum number of EVs the grid can handle before voltage drops below 0.90 p.u.
- **Reliability Assessment:** Calculates SAIDI, SAIFI, and CAIDI indices using topology-aware downstream tracing.
- **FVSI Stability:** Predicts voltage collapse proximity.
- **Visual Topology Map:** Draws the actual grid structure, including open tie-switches and source buses.

## 📂 Included Test Feeders
GridGuard comes with several real-world test cases to prove its universal engine:
- IEEE 33-Bus (Standard Academic Test)
- Bangladesh (11kV / 0.4kV, Dense Load)
- Norway (22kV / 0.4kV, Long Distances)
- Japan (6.6kV / 0.2kV, Underground)
- USA (12.47kV / 0.24kV, Overhead)
- Australia (11kV / 0.4kV, Rural)
- Middle East (33kV / 11kV / 0.4kV, Industrial)
- oberrhein (a german regional medium-voltage grid that ships with pandapower)
- SimBench urban grid (closet to a city)

## 🛠️ Installation & Usage

1. Clone this repository:
   ```bash
   git clone https://github.com/iftimohammed2k2/GridGuard.git
   cd GridGuard
```

2. Create a virtual environment and activate it:
   ```bash
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1  # Windows
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the Zenithic Command Center:
   ```bash
   streamlit run app.py
   ```
5. Upload your buses.csv and lines.csv, set the units in the sidebar, and click Run Full Analysis.

📊 Supported CSV Formats

Your buses.csv must have: id, nominal_kv, is_slack, load_p_mw, load_q_mvar.
Your lines.csv must have: id, from_bus, to_bus, length_km, r_ohm_per_km, x_ohm_per_km, max_i_ka.

Note: GridGuard automatically handles column name variations (e.g., Bus_ID, Pd, RateA) and unit conversions.

⚠️ Disclaimer

GridGuard is a screening tool. It is not a replacement for full commercial softwares like ETAP or CYME or a certified safety study. All results should be reviewed by a qualified engineer.

---

GridGuard is an engineering software by Zenithic. Designed and built by Ifti Mohammed Muntakim.

```

