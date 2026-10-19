import streamlit as st
import subprocess
import sys
import tempfile
import json
import random
import re
from pathlib import Path
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import networkx as nx

ROOT = Path(__file__).resolve().parent
st.set_page_config(
    layout="wide",
    page_title="GridGuard by Zenithic | Power Systems Analysis",
    page_icon="⚡",
)

# ─────────────────────────────  THEME  ─────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=DM+Sans:wght@300;400;500;600;700&display=swap');

:root {
    --ink: #EAF0FF;
    --muted: #94A3C4;
    --panel: rgba(16, 24, 52, 0.62);
    --panel-edge: rgba(129, 160, 255, 0.18);
    --spark: #FBBF24;
    --volt: #38BDF8;
}

.stApp {
    font-family: 'DM Sans', sans-serif;
    color: var(--ink);
    background-color: #050816;
    background-image:
        radial-gradient(900px 500px at 12% -5%, rgba(139, 92, 246, 0.35), transparent 60%),
        radial-gradient(800px 520px at 95% 8%, rgba(56, 189, 248, 0.28), transparent 60%),
        radial-gradient(700px 480px at 50% 110%, rgba(251, 191, 36, 0.14), transparent 65%),
        linear-gradient(rgba(129, 160, 255, 0.045) 1px, transparent 1px),
        linear-gradient(90deg, rgba(129, 160, 255, 0.045) 1px, transparent 1px);
    background-size: auto, auto, auto, 46px 46px, 46px 46px;
    background-attachment: fixed;
}

h1, h2, h3, h4 {
    font-family: 'Space Grotesk', sans-serif !important;
    color: #F5F8FF;
    font-weight: 600;
    letter-spacing: -0.4px;
}

.glass-panel { display: none; }  /* empty wrapper; tab content is styled by Streamlit itself */

div[data-testid="stMetric"] {
    background: var(--panel);
    backdrop-filter: blur(10px);
    border: 1px solid var(--panel-edge);
    border-left: 3px solid var(--spark);
    border-radius: 12px;
    padding: 16px;
}
div[data-testid="stMetric"] label {
    font-size: 0.82rem;
    color: var(--muted) !important;
    font-weight: 500;
    letter-spacing: 0.3px;
}
div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
    font-family: 'Space Grotesk', sans-serif;
    color: var(--volt) !important;
    font-weight: 700;
    font-size: 1.9rem;
}
div[data-testid="stMetric"] div[data-testid="stMetricValue"] > div,
div[data-testid="stMetric"] label p {
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: clip !important;
}

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0A1030 0%, #060A1F 100%);
    border-right: 1px solid var(--panel-edge);
}
[data-testid="stSidebar"] .stButton>button {
    background: linear-gradient(135deg, #F59E0B 0%, #FBBF24 100%);
    color: #1A1203;
    border: none;
    border-radius: 10px;
    font-weight: 700;
    padding: 12px;
    box-shadow: 0 6px 20px -6px rgba(251, 191, 36, 0.55);
    transition: transform .15s ease, box-shadow .15s ease;
}
[data-testid="stSidebar"] .stButton>button:hover {
    transform: translateY(-1px);
    box-shadow: 0 10px 26px -6px rgba(251, 191, 36, 0.7);
    color: #1A1203;
}
[data-testid="stFileUploader"] section {
    background: rgba(16, 24, 52, 0.55);
    border: 1px dashed rgba(129, 160, 255, 0.35);
    border-radius: 12px;
}

button[data-baseweb="tab"] { font-family: 'Space Grotesk', sans-serif; font-weight: 500; color: var(--muted); }
button[data-baseweb="tab"][aria-selected="true"] { color: var(--spark); }
div[data-baseweb="tab-highlight"] { background-color: var(--spark) !important; }

.zen-badge {
    display: inline-block; padding: 4px 12px; border-radius: 999px;
    background: rgba(251, 191, 36, 0.12); border: 1px solid rgba(251, 191, 36, 0.4);
    color: var(--spark); font-size: 0.82rem; font-weight: 600; letter-spacing: 0.3px;
}
.hero-title {
    font-family: 'Space Grotesk', sans-serif; font-weight: 700;
    font-size: clamp(2.6rem, 6vw, 4.4rem); line-height: 1.02; letter-spacing: -2px;
    margin: 14px 0 6px 0;
    background: linear-gradient(100deg, #FFFFFF 10%, #7DD3FC 55%, #FBBF24 100%);
    -webkit-background-clip: text; background-clip: text; color: transparent;
}
.hero-sub { color: var(--muted); font-size: 1.15rem; max-width: 640px; line-height: 1.55; }
.step-card {
    background: var(--panel); border: 1px solid var(--panel-edge);
    border-radius: 14px; padding: 20px; height: 100%;
}
.step-card b { font-family: 'Space Grotesk', sans-serif; color: #F5F8FF; font-size: 1.05rem; }
.step-card p { color: var(--muted); margin: 6px 0 0 0; font-size: 0.95rem; line-height: 1.5; }
.fact-card {
    background: var(--panel); backdrop-filter: blur(10px);
    padding: 18px 20px; border-radius: 14px; border: 1px solid var(--panel-edge);
    border-left: 4px solid var(--spark); margin-top: 20px;
}
.zen-footer { text-align: center; color: var(--muted); font-size: 0.85rem; padding: 28px 0 8px 0; }

#MainMenu {visibility: hidden;} footer {visibility: hidden;}
header {background: transparent !important;}
</style>
""", unsafe_allow_html=True)

PLOT_STYLE = dict(
    plot_bgcolor='rgba(0,0,0,0)',
    paper_bgcolor='rgba(0,0,0,0)',
    font=dict(color="#EAF0FF", family="DM Sans"),
)

# ─────────────────────────  LOADING CONTENT  ─────────────────────────
GRID_FACTS = [
    "Edison's Pearl Street Station in New York switched on in 1882 and powered about 400 lamps at first.",
    "A power grid has to balance supply and demand every single second. Frequency is how it keeps score.",
    "Electrons in a copper wire drift at less than a millimetre per second. The energy travels far faster.",
    "Transmitting at high voltage cuts losses because heat loss grows with the square of the current.",
    "Transformers have no moving parts, which is why some run reliably for 40 years or more.",
    "Power lines sag in summer heat. That is why a line's safe current limit changes with the weather.",
    "One fast EV charger can draw as much power as a small block of homes.",
    "Most distribution feeders are built as radial trees, so one fault can leave everything downstream dark.",
]

SCRIPTS = [
    "integrity_checker.py", "powerflow_checker.py",
    "thermal_loading_checker.py", "ev_scenario_analyzer.py",
    "short_circuit_checker.py", "reliability_checker.py",
]

STAGE_TITLES = [
    "Checking that your network is wired correctly",
    "Solving the voltage picture across every bus",
    "Testing how hot your lines can safely run",
    "Plugging in EVs until the grid pushes back",
    "Measuring what a fault would do",
    "Estimating how often customers lose power",
]

OUTPUT_FILES = [
    "integrity_summary.json", "baseline_summary.json", "thermal_summary.json",
    "ev_scenario_summary.json", "baseline_bus_results.csv",
    "short_circuit_summary.json", "reliability_summary.json"
]

IMPEDANCE_LABELS = {
    "ohm/km": "Ohm per km",
    "ohm": "Ohm, total per line",
    "pu": "Per-unit",
}


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(s))]


# Results are only shown after a run in the current session
if "analysis_done" not in st.session_state:
    st.session_state["analysis_done"] = False

# ─────────────────────────────  SIDEBAR  ─────────────────────────────
with st.sidebar:
    st.markdown("<span class='zen-badge'>⚡ ZENITHIC</span>", unsafe_allow_html=True)
    st.markdown("### GridGuard")
    st.markdown("<p style='color: #94A3C4; font-size: 0.9rem;'>Power systems analysis, by Zenithic</p>", unsafe_allow_html=True)
    st.markdown("---")

    st.markdown("#### Upload your network")
    bus_file = st.file_uploader("Upload buses.csv", type=["csv"])
    line_file = st.file_uploader("Upload lines.csv", type=["csv"])

    with st.expander("Data units and source", expanded=False):
        st.caption("Tell GridGuard how your files are measured. Units written in a column header, such as P_kW, override these.")
        load_unit = st.selectbox("Load units", ["MW", "kW"])
        length_unit = st.selectbox("Line length units", ["km", "m", "mi"])
        imp_unit = st.selectbox("Line R and X units", list(IMPEDANCE_LABELS.keys()),
                                format_func=lambda k: IMPEDANCE_LABELS[k])
        if imp_unit == "pu":
            base_mva = st.number_input("Base power (MVA) for per-unit data", min_value=0.1, value=100.0)
        else:
            base_mva = 100.0
        source_mva = st.number_input("Source short-circuit level (MVA)", min_value=1.0, value=100.0)

    st.markdown("---")

    if st.button("Run Full Analysis", type="primary", use_container_width=True):
        if bus_file and line_file:
            st.session_state["analysis_done"] = False
            for f in OUTPUT_FILES:
                p = ROOT / f
                if p.exists(): p.unlink()

            with tempfile.TemporaryDirectory() as td:
                td = Path(td)
                bp = td / "buses.csv"
                lp = td / "lines.csv"
                bp.write_bytes(bus_file.getvalue())
                lp.write_bytes(line_file.getvalue())

                common_args = [
                    "--buses-csv", str(bp), "--lines-csv", str(lp),
                    "--load-unit", load_unit, "--length-unit", length_unit,
                    "--impedance-unit", imp_unit, "--base-mva", str(base_mva),
                ]

                progress_bar = st.progress(0)
                status_text = st.empty()
                quote_text = st.empty()

                facts = random.sample(GRID_FACTS, k=len(SCRIPTS))

                for i, script in enumerate(SCRIPTS):
                    quote_text.markdown(f"""
                        <div class='fact-card'>
                            <p style='font-size: 0.85rem; color: #FBBF24; margin: 0 0 6px 0; font-weight: 600;'>
                                Did you know?
                            </p>
                            <p style='color: #EAF0FF; margin: 0 0 12px 0; line-height: 1.5;'>{facts[i]}</p>
                            <hr style='margin: 10px 0; border-color: rgba(129,160,255,0.2);'>
                            <p style='font-size: 0.8rem; color: #94A3C4; margin: 0;'>
                                GridGuard by <b style='color:#FBBF24;'>Zenithic</b><br>
                                Zenithic is founded by Ifti Mohammed Muntakim, an Electrical and Electronics Engineering Student from Bangladesh
                            </p>
                        </div>
                    """, unsafe_allow_html=True)

                    status_text.info(f"{STAGE_TITLES[i]}...")

                    cmd = [sys.executable, str(ROOT / script)] + common_args
                    if script == "short_circuit_checker.py":
                        cmd += ["--source-mva", str(source_mva)]

                    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))

                    if res.returncode != 0:
                        st.error(f"❌ Execution Error in `{script}`")
                        st.code(res.stderr)
                        st.stop()
                    progress_bar.progress((i + 1) / len(SCRIPTS))

                status_text.success("✅ Analysis complete. Your grid report is ready.")
                st.session_state["analysis_done"] = True
                st.rerun()
        else:
            st.error("Please upload both CSVs.")

# ─────────────────────────────  MAIN  ─────────────────────────────
if st.session_state["analysis_done"] and all((ROOT / f).exists() for f in OUTPUT_FILES):
    try:
        integ = json.loads((ROOT / "integrity_summary.json").read_text())
        pf = json.loads((ROOT / "baseline_summary.json").read_text())
        therm = json.loads((ROOT / "thermal_summary.json").read_text())
        ev_data = json.loads((ROOT / "ev_scenario_summary.json").read_text())
        sc_data = json.loads((ROOT / "short_circuit_summary.json").read_text())
        rel_data = json.loads((ROOT / "reliability_summary.json").read_text())
    except Exception as e:
        st.error(f"Failed to load result files: {e}")
        st.stop()

    st.markdown("<span class='zen-badge'>⚡ GridGuard by Zenithic</span>", unsafe_allow_html=True)
    st.markdown("<h1 style='margin-bottom: 0;'>System Telemetry</h1>", unsafe_allow_html=True)
    st.markdown("<p style='color: #94A3C4; font-size: 1.1rem; margin-top: 5px;'>Your grid analysis dashboard</p>", unsafe_allow_html=True)

    if pf.get("converged") is False:
        st.error(
            "The power flow did not converge, so voltage, loss and loading results are unavailable. "
            "This usually means a unit mismatch (kW read as MW, ohm read as ohm/km), a load that is too "
            "heavy for the feeder, or a missing source. Check the units in the sidebar and the data "
            "report in the Integrity tab."
        )
        if pf.get("error"):
            st.caption(f"Solver detail: {pf['error']}")
    st.markdown("---")

    st.subheader("System Metrics")
    pf_metrics = pf.get("metrics", {})
    rel_metrics = rel_data.get("metrics", {})
    exact_ev = ev_data.get('exact_max_hosting_capacity', 0)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Min Voltage", f"{pf_metrics.get('min_voltage_pu', 'N/A')} pu")
    m2.metric("Network Loss", f"{pf_metrics.get('total_network_loss_mw', 'N/A')} MW")
    m3.metric("Reactive Loss", f"{pf_metrics.get('reactive_loss_pct', 'N/A')}%")
    m4.metric("Exact EV Capacity", f"{exact_ev} EVs")

    n1, n2, n3, n4 = st.columns(4)
    n1.metric("SAIDI", f"{rel_metrics.get('SAIDI', 'N/A')} hrs/yr")
    n2.metric(f"Fault at Source (bus {sc_data.get('critical_bus', '?')})",
              f"{sc_data.get('max_fault_current_ka', 'N/A')} kA")
    n3.metric(f"Lowest Fault (bus {sc_data.get('min_bus', '?')})",
              f"{sc_data.get('min_fault_current_ka', 'N/A')} kA")

    st.markdown("---")

    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "Integrity", "Power Flow & FVSI", "Thermal Dynamics",
        "EV Hosting Capacity", "Short-Circuit", "Reliability", "Topology"
    ])

    # ---- Integrity ----
    with tab1:
        st.markdown("<div class='glass-panel'>", unsafe_allow_html=True)
        st.subheader("Network Data Integrity")
        status = integ.get("status")
        if status == "FAIL":
            st.error("The network files could not be read.")
            for msg in integ.get("errors", []):
                st.write(f"• {msg}")
        elif status == "PASS":
            st.success("Network is connected and structurally valid.")
        else:
            st.warning("Network has disconnected components or topology issues.")
        for msg in integ.get("warnings", []):
            st.warning(msg)

        integ_metrics = integ.get("metrics", {})
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Buses", integ_metrics.get("bus_count", "N/A"))
        c2.metric("Total Branches", integ_metrics.get("line_count", "N/A"))
        c3.metric("Radial Topology?", "Yes" if integ_metrics.get("is_radial") else "No (Meshed)")
        c4.metric("Open Tie Switches", integ_metrics.get("open_branches", 0))

        report = integ.get("report", [])
        if report:
            with st.expander(f"Data loading report ({len(report)} notes)", expanded=status != "PASS"):
                for line in report:
                    st.write(f"• {line}")
        st.markdown("</div>", unsafe_allow_html=True)

    # ---- Power flow ----
    with tab2:
        st.markdown("<div class='glass-panel'>", unsafe_allow_html=True)
        st.subheader("Fast Voltage Stability Index (FVSI)")
        fvsi_data = pf.get("fvsi_analysis", [])
        if fvsi_data:
            fvsi_df = pd.DataFrame(fvsi_data)
            def style_fvsi(val): return 'color: #ef4444; font-weight: bold;' if val == "UNSTABLE" else 'color: #10b981;'
            st.dataframe(fvsi_df.style.map(style_fvsi, subset=["status"]), use_container_width=True)
            fig_fvsi = px.bar(fvsi_df, x="line", y="fvsi", color="status", color_discrete_map={"STABLE": "#10b981", "UNSTABLE": "#ef4444"}, title="FVSI Proximity to Collapse (Limit = 1.0)")
            fig_fvsi.add_hline(y=1.0, line_dash="dash", line_color="#ef4444")
            fig_fvsi.update_layout(**PLOT_STYLE)
            st.plotly_chart(fig_fvsi, use_container_width=True)
        else: st.info("No FVSI data found.")
        st.markdown("</div>", unsafe_allow_html=True)

    # ---- Thermal ----
    with tab3:
        st.markdown("<div class='glass-panel'>", unsafe_allow_html=True)
        st.subheader("Dynamic Thermal Rating (simplified ambient and wind model)")
        t_data = therm.get("equipment", [])
        if t_data:
            t_df = pd.DataFrame(t_data)
            st.info(f"Ratings adjusted for Ambient Temp: {therm.get('ambient_temp_c', 35)}°C | Wind: {therm.get('wind_speed_m_s', 0.61)} m/s")
            if therm.get("overloads"):
                st.warning(f"{therm['overloads']} line(s) are loaded above their dynamic rating.")
            fig_t = go.Figure()
            fig_t.add_trace(go.Bar(x=t_df["id"], y=t_df["base_rating_ka"], name="Static Rating", marker_color='#64748B'))
            fig_t.add_trace(go.Bar(x=t_df["id"], y=t_df["dynamic_rating_ka"], name="Dynamic Rating", marker_color='#38BDF8'))
            fig_t.add_trace(go.Scatter(x=t_df["id"], y=t_df["current_ka"], mode='markers', name="Actual Current", marker=dict(color='#FBBF24', size=10)))
            fig_t.update_layout(barmode='group', title="Thermal Ratings vs Actual Current", **PLOT_STYLE)
            st.plotly_chart(fig_t, use_container_width=True)
        else: st.info("No thermal data found.")
        st.markdown("</div>", unsafe_allow_html=True)

    # ---- EV hosting ----
    with tab4:
        st.markdown("<div class='glass-panel'>", unsafe_allow_html=True)
        st.subheader("Probabilistic EV Hosting Capacity")

        if ev_data.get("status") == "FAIL":
            st.error(ev_data.get("error", "The EV analysis could not run."))
        else:
            if ev_data.get("baseline_violation"):
                st.warning(
                    "The network already breaks the voltage limit with no EVs connected, "
                    "so the hosting capacity is 0. Fix the base-case voltage first."
                )
            st.success(f"### 🎯 **Exact Maximum Hosting Capacity: {exact_ev} EVs**")
            if ev_data.get("capped"):
                st.info(f"The search stopped at {ev_data.get('max_evs_searched', 2000)} EVs. The real capacity may be higher.")
            weak = ev_data.get("weak_buses")
            if weak:
                st.caption("EV charging is placed on the weakest buses: " + ", ".join(weak))

            ev_scenarios = ev_data.get("scenarios", [])
            if ev_scenarios:
                df_sweep = pd.DataFrame([{
                    "EVs": s.get("ev_count"), "Worst Voltage": s.get("worst_min_voltage"),
                    "Violation Probability (%)": s.get("violation_probability_pct"), "Status": s.get("status")
                } for s in ev_scenarios])
                status_colors = {"PASS": "#10b981", "FAIL": "#ef4444", "EXACT LIMIT": "#FBBF24"}
                v_limit = ev_data.get("voltage_limit_pu", 0.90)
                risk = ev_data.get("risk_threshold_pct", 20)

                colA, colB = st.columns(2)
                with colA:
                    fig_v = px.line(df_sweep, x="EVs", y="Worst Voltage", markers=True, color="Status", color_discrete_map=status_colors)
                    fig_v.add_hline(y=v_limit, line_dash="dash", line_color="#ef4444", annotation_text=f"{v_limit:g} p.u. Limit")
                    fig_v.update_layout(title="Worst-Case Voltage vs EV Penetration", **PLOT_STYLE)
                    st.plotly_chart(fig_v, use_container_width=True)
                with colB:
                    fig_p = px.bar(df_sweep, x="EVs", y="Violation Probability (%)", color="Status", color_discrete_map=status_colors)
                    fig_p.add_hline(y=risk, line_dash="dash", line_color="#f59e0b", annotation_text=f"{risk:g}% Risk Threshold")
                    fig_p.update_layout(title="Probability of Voltage Violation", **PLOT_STYLE)
                    st.plotly_chart(fig_p, use_container_width=True)
                st.caption(f"Each scenario is tested with {ev_data.get('seeds', 5)} random charging patterns. "
                           "An hour where the power flow fails to converge counts as a violation.")
        st.markdown("</div>", unsafe_allow_html=True)

    # ---- Short-circuit ----
    with tab5:
        st.markdown("<div class='glass-panel'>", unsafe_allow_html=True)
        st.subheader("Short-Circuit Analysis (IEC 60909)")
        sc_results = sc_data.get("all_buses", [])
        if sc_results:
            df_sc = pd.DataFrame(sc_results)
            df_sc["bus_id"] = df_sc["bus_id"].astype(str)

            # Natural order so the chart reads Bus 1, Bus 2, ..., Bus 10
            order = sorted(df_sc["bus_id"].tolist(), key=natural_key)
            df_sc = df_sc.set_index("bus_id").loc[order].reset_index()

            fig_sc = px.bar(
                df_sc, x="bus_id", y="fault_current_ka",
                title="3-Phase Fault Current by Bus",
                color_discrete_sequence=['#38BDF8'],
                text="fault_current_ka"
            )
            fig_sc.update_traces(texttemplate='%{text} kA', textposition='outside')
            fig_sc.update_xaxes(type="category", categoryorder="array", categoryarray=order)

            if df_sc["fault_current_ka"].max() > 100 and df_sc["fault_current_ka"].min() > 0:
                fig_sc.update_layout(yaxis_type="log", yaxis_title="Fault Current (kA) - Log Scale")

            fig_sc.update_layout(
                xaxis_title="Bus ID",
                yaxis_title="Fault Current (kA)",
                **PLOT_STYLE
            )
            st.plotly_chart(fig_sc, use_container_width=True)
            st.caption(
                f"Maximum 3-phase fault with an upstream source of {sc_data.get('source_mva', 100):g} MVA. "
                "The highest value is always at the source bus (source MVA divided by root-3 times kV), "
                "so it only changes with the source setting. The lowest value, at the electrically "
                "farthest bus, shows how weak the fault level gets along the feeder."
            )
            if sc_data.get("unreachable_count"):
                st.warning(f"{sc_data['unreachable_count']} bus(es) are not connected to the source and were left out.")
        elif sc_data.get("status") == "FAIL":
            st.warning(f"Short-circuit calculation failed: {sc_data.get('error', 'unknown error')}")
        else:
            st.warning("No short-circuit data found.")
        st.markdown("</div>", unsafe_allow_html=True)

    # ---- Reliability ----
    with tab6:
        st.markdown("<div class='glass-panel'>", unsafe_allow_html=True)
        st.subheader("Reliability Assessment")
        rel_m = rel_data.get("metrics", {})
        if rel_m:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("SAIFI", f"{rel_m.get('SAIFI', 0)} int/cust-yr")
            c2.metric("SAIDI", f"{rel_m.get('SAIDI', 0)} hrs/cust-yr")
            c3.metric("CAIDI", f"{rel_m.get('CAIDI', 0)} hrs/int")
            c4.metric("Customers", rel_m.get("Customers", 0))
            for note in rel_data.get("assumptions", []):
                st.caption(f"• {note}")
        st.markdown("</div>", unsafe_allow_html=True)

    # ---- Topology ----
    with tab7:
        st.markdown("<div class='glass-panel'>", unsafe_allow_html=True)
        st.subheader("Visual Topology Map")

        topo = integ.get("topology")
        if topo and topo.get("nodes"):
            try:
                G = nx.Graph()
                G.add_nodes_from(topo["nodes"])
                closed_edges = [(e["from"], e["to"]) for e in topo["edges"] if e["in_service"]]
                open_edges = [(e["from"], e["to"]) for e in topo["edges"] if not e["in_service"]]
                G.add_edges_from(closed_edges + open_edges)
                pos = nx.spring_layout(G, seed=42)

                def edge_trace(edges, **line):
                    xs, ys = [], []
                    for a, b in edges:
                        x0, y0 = pos[a]; x1, y1 = pos[b]
                        xs.extend([x0, x1, None]); ys.extend([y0, y1, None])
                    return go.Scatter(x=xs, y=ys, mode='lines', line=line, hoverinfo='skip')

                slack = topo.get("slack")
                others = [n for n in G.nodes() if n != slack]

                fig_topo = go.Figure()
                fig_topo.add_trace(edge_trace(closed_edges, width=1.5, color='#5B6B9A'))
                if open_edges:
                    fig_topo.add_trace(edge_trace(open_edges, width=1.5, color='#FBBF24', dash='dash'))
                fig_topo.add_trace(go.Scatter(
                    x=[pos[n][0] for n in others], y=[pos[n][1] for n in others],
                    mode='markers+text', text=others, textposition="bottom center",
                    marker=dict(size=11, color='#38BDF8', line=dict(width=1.5, color='#FFFFFF'))
                ))
                if slack in pos:
                    fig_topo.add_trace(go.Scatter(
                        x=[pos[slack][0]], y=[pos[slack][1]], mode='markers+text',
                        text=[f"{slack} (source)"], textposition="bottom center",
                        marker=dict(size=18, color='#FBBF24', symbol='diamond', line=dict(width=2, color='#FFFFFF'))
                    ))
                fig_topo.update_layout(
                    showlegend=False,
                    xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                    yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                    height=520,
                    **PLOT_STYLE
                )
                st.plotly_chart(fig_topo, use_container_width=True)
                if open_edges:
                    st.caption("Dashed amber lines are open tie switches.")
            except Exception:
                st.info("The topology map could not be drawn for this network.")
        else:
            st.info("No topology data available.")

        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='zen-footer'>GridGuard is a product of <b style='color:#FBBF24;'>Zenithic</b></div>", unsafe_allow_html=True)

else:
    # ─────────────  Landing page (first visit, no old results)  ─────────────
    st.markdown("<span class='zen-badge'>⚡ A product of Zenithic</span>", unsafe_allow_html=True)
    st.markdown("<div class='hero-title'>GridGuard</div>", unsafe_allow_html=True)
    st.markdown(
        "<p class='hero-sub'>See how your distribution network holds up before the load arrives. "
        "Voltage, heat, faults, reliability and EV hosting capacity, all from two CSV files.</p>",
        unsafe_allow_html=True,
    )
    st.markdown("<br>", unsafe_allow_html=True)

    s1, s2, s3 = st.columns(3)
    s1.markdown("<div class='step-card'><b>1. Upload</b><p>Add buses.csv and lines.csv from the sidebar, and set their units.</p></div>", unsafe_allow_html=True)
    s2.markdown("<div class='step-card'><b>2. Run</b><p>Press Run Full Analysis and GridGuard works through the whole network.</p></div>", unsafe_allow_html=True)
    s3.markdown("<div class='step-card'><b>3. Explore</b><p>Open the dashboard to see risks, limits and exact EV capacity.</p></div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.info("Waiting for your data. Upload buses.csv and lines.csv in the sidebar, then click 'Run Full Analysis'.")
    st.markdown("<div class='zen-footer'>GridGuard is an engineering software by <b style='color:#FBBF24;'>Zenithic</b></div>", unsafe_allow_html=True)