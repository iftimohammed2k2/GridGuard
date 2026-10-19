"""GridGuard network builder (Zenithic).

Reads a buses CSV and a lines CSV in many common layouts and builds a
pandapower network. Everything it assumes, converts or skips is recorded in
net["gg_report"] so the dashboard can show it.
"""
import argparse
import csv
import io
import logging
import math
from pathlib import Path

import pandapower as pp

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("gridguard")

# ---------------------------------------------------------------------------
# Column aliases. Headers are lower-cased and stripped of everything except
# letters and digits before matching, so "Load_P (kW)" becomes "loadpkw".
# The ORDER of each list is the priority order.
# ---------------------------------------------------------------------------
BUS_ALIASES = {
    "id": ["id", "bus", "busid", "busname", "busnumber", "busno", "nodeid", "node", "number", "name"],
    "kv": ["nominalkv", "vnkv", "kv", "basekv", "voltagekv", "nomkv", "vbase", "vn", "voltage"],
    "p": ["loadpmw", "loadpkw", "pmw", "pkw", "pd", "pload", "loadp", "p", "activepower", "load", "kw", "mw"],
    "q": ["loadqmvar", "loadqkvar", "qmvar", "qkvar", "qd", "qload", "loadq", "q", "reactivepower", "kvar", "mvar"],
    "slack": ["isslack", "slack", "slackbus", "isref", "refbus", "reference"],
    "type": ["bustype", "type"],
    "customers": ["customers", "numcustomers", "ncustomers", "custcount", "consumers", "numconsumers"],
}

LINE_ALIASES = {
    "id": ["id", "lineid", "linename", "branchid", "branch", "line", "name"],
    "from": ["frombus", "from", "fbus", "fromnode", "startbus", "start", "sendingbus", "busfrom", "bus1", "node1"],
    "to": ["tobus", "to", "tbus", "tonode", "endbus", "end", "receivingbus", "busto", "bus2", "node2"],
    "length": ["lengthkm", "lengthm", "lengthmi", "lengthmiles", "lengthmeters", "lengthmetres",
               "lenkm", "length", "len", "distancekm", "distance", "dist"],
    "r": ["rohmperkm", "rohmkm", "rohm", "rpu", "rtotal", "r1", "resistance", "r"],
    "x": ["xohmperkm", "xohmkm", "xohm", "xpu", "xtotal", "x1", "reactance", "x"],
    "rating": ["maxika", "ratingka", "imaxka", "ratea", "rating", "maxcurrent", "imax", "imaxa", "maxia", "ampacity", "limit"],
    "status": ["inservice", "status", "closed", "isclosed", "switchstatus", "switch", "state", "normalstatus"],
    "sn": ["snmva", "ratingmva", "smva", "mva"],
    "vk": ["vkpercent", "ukpercent", "uk"],
    "vkr": ["vkrpercent", "ukrpercent"],
}

TRUE_WORDS = {"true", "1", "yes", "y", "t", "slack", "ref"}
OPEN_WORDS = {"0", "false", "no", "open", "opened", "off", "n", "f", "out"}
CLOSED_WORDS = {"1", "true", "yes", "closed", "close", "on", "y", "t", "in", "nc"}

MIN_IMPEDANCE_OHM_PER_KM = 1e-4
DEFAULT_RATING_KA = 0.4
DEFAULT_KV = 11.0
DEFAULT_R_X_OHM_PER_KM = 0.1


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _norm(s):
    return "".join(c for c in str(s).lower() if c.isalnum())


def _safe_float(val, default=None):
    """Parse a number; handles 1,5 / 1,234.5 / blanks / nan / inf."""
    if val is None:
        return default
    s = str(val).strip()
    if not s:
        return default
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    elif "," in s:
        s = s.replace(",", "")
    try:
        f = float(s)
    except ValueError:
        return default
    return f if math.isfinite(f) else default


def _clean_id(val):
    """'1.0' -> '1', ' B7 ' -> 'B7'."""
    s = str(val if val is not None else "").strip()
    try:
        f = float(s)
        if math.isfinite(f) and f.is_integer():
            return str(int(f))
    except ValueError:
        pass
    return s


class Report:
    """Collects notes; per-row issues are aggregated into one line each."""

    def __init__(self):
        self.lines = []
        self._agg = {}

    def add(self, msg):
        self.lines.append(msg)

    def agg(self, key, example=None):
        count, first = self._agg.get(key, (0, example))
        self._agg[key] = (count + 1, first if count else example)

    def finish(self):
        out = list(self.lines)
        for key, (count, example) in self._agg.items():
            tail = f", e.g. {example}" if example else ""
            out.append(f"{key} ({count} row{'s' if count != 1 else ''}{tail})")
        return out


def _read_table(path):
    """Return (headers, rows) with delimiter and encoding auto-detected."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    headers = None
    rows = []
    for cells in reader:
        if not any(c.strip() for c in cells):
            continue
        if headers is None:
            headers = [c.strip() for c in cells]
            continue
        if cells and cells[0].strip().startswith("#"):
            continue
        rows.append({h: (cells[i].strip() if i < len(cells) else "")
                     for i, h in enumerate(headers) if h})
    if headers is None:
        raise ValueError(f"{Path(path).name} is empty")
    return headers, rows


def _resolve(headers, aliases):
    norm_map = {}
    for h in headers:
        norm_map.setdefault(_norm(h), h)
    found = {}
    for field, names in aliases.items():
        found[field] = next((norm_map[n] for n in names if n in norm_map), None)
    return found


def _power_scale(header, default_unit):
    """Multiplier that converts the column to MW / MVAr."""
    h = _norm(header) if header else ""
    if "kw" in h or "kvar" in h or "kva" in h:
        return 1e-3, "kW"
    if "mw" in h or "mvar" in h or "mva" in h:
        return 1.0, "MW"
    return (1e-3, "kW") if default_unit == "kW" else (1.0, "MW")


def _length_scale(header, default_unit):
    """Multiplier that converts the column to km."""
    h = _norm(header) if header else ""
    if h.endswith("km"):
        return 1.0, "km"
    if h.endswith("miles") or h.endswith("mi"):
        return 1.609344, "mi"
    if h.endswith("meters") or h.endswith("metres") or h.endswith("m"):
        return 1e-3, "m"
    return {"km": 1.0, "m": 1e-3, "mi": 1.609344}.get(default_unit, 1.0), default_unit


def _impedance_mode(header, default_mode):
    h = _norm(header) if header else ""
    if h.endswith("pu"):
        return "pu"
    if "perkm" in h or "ohmkm" in h:
        return "ohm/km"
    return default_mode


def _to_ohm_per_km(val, mode, length_km, z_base):
    if val is None:
        return DEFAULT_R_X_OHM_PER_KM
    if mode == "pu":
        return val * z_base / length_km
    if mode == "ohm":
        return val / length_km
    return val


# ---------------------------------------------------------------------------
# Command-line plumbing shared by every checker script
# ---------------------------------------------------------------------------
def add_common_args(parser):
    parser.add_argument("--buses-csv", required=True)
    parser.add_argument("--lines-csv", required=True)
    parser.add_argument("--load-unit", choices=["MW", "kW"], default="MW")
    parser.add_argument("--length-unit", choices=["km", "m", "mi"], default="km")
    parser.add_argument("--impedance-unit", choices=["ohm/km", "ohm", "pu"], default="ohm/km")
    parser.add_argument("--base-mva", type=float, default=100.0)
    return parser


def units_from_args(args):
    return {
        "load": args.load_unit,
        "length": args.length_unit,
        "impedance": args.impedance_unit,
        "base_mva": args.base_mva,
    }


# ---------------------------------------------------------------------------
# Network construction
# ---------------------------------------------------------------------------
def build_network(buses_path, lines_path, units=None):
    """Build a pandapower net. The data-loading report is in net["gg_report"]."""
    u = {"load": "MW", "length": "km", "impedance": "ohm/km", "base_mva": 100.0}
    if units:
        u.update(units)
    rep = Report()
    rep.add(f"Units selected: load {u['load']}, length {u['length']}, "
            f"R/X {u['impedance']}, base {u['base_mva']:g} MVA. "
            "Units written in a column header override these.")

    # ---------------- buses ----------------
    b_headers, b_rows = _read_table(buses_path)
    bc = _resolve(b_headers, BUS_ALIASES)
    if bc["id"] is None:
        rep.add("buses file: no ID column recognised, buses numbered by row (B0, B1, ...)")
    if bc["kv"] is None:
        rep.add(f"buses file: no voltage column recognised, assuming {DEFAULT_KV:g} kV everywhere")
    if bc["p"] is None:
        rep.add("buses file: no active-power column recognised, all loads are zero")
    if bc["q"] is None:
        rep.add("buses file: no reactive-power column recognised, reactive load is zero")

    p_scale, p_unit = _power_scale(bc["p"], u["load"])
    q_scale, q_unit = _power_scale(bc["q"], u["load"])
    if bc["p"] and p_unit != u["load"]:
        rep.add(f"buses file: column '{bc['p']}' read as {p_unit} from its header")
    if bc["q"] and q_unit != u["load"]:
        rep.add(f"buses file: column '{bc['q']}' read as {q_unit} from its header")

    buses = []
    seen = {}
    for i, r in enumerate(b_rows):
        raw_id = r.get(bc["id"], "") if bc["id"] else ""
        bid = _clean_id(raw_id) if raw_id.strip() else f"B{i}"
        base = bid
        if base in seen:
            seen[base] += 1
            bid = f"{base}#{seen[base]}"
            rep.agg("Duplicate bus ID renamed", base)
        seen.setdefault(bid, 1)

        kv = _safe_float(r.get(bc["kv"])) if bc["kv"] else None
        if kv is None or kv <= 0:
            if bc["kv"]:
                rep.agg(f"Blank or invalid bus voltage replaced by {DEFAULT_KV:g} kV", bid)
            kv = DEFAULT_KV
        elif kv > 1000:
            kv /= 1000.0
            rep.agg("Bus voltage above 1000 read as volts and converted to kV", bid)

        p = (_safe_float(r.get(bc["p"]), 0.0) if bc["p"] else 0.0) * p_scale
        q = (_safe_float(r.get(bc["q"]), 0.0) if bc["q"] else 0.0) * q_scale

        is_slack = False
        if bc["slack"]:
            is_slack = _clean_id(r.get(bc["slack"], "")).lower() in TRUE_WORDS
        if bc["type"] and _clean_id(r.get(bc["type"], "")).lower() in ("slack", "ref", "reference", "3"):
            is_slack = True

        cust = _safe_float(r.get(bc["customers"])) if bc["customers"] else None
        buses.append({"id": bid, "kv": kv, "p": p, "q": q, "slack": is_slack, "customers": cust})

    if not buses:
        raise ValueError("The buses file has no readable rows.")

    slacks = [b for b in buses if b["slack"]]
    if not slacks:
        buses[0]["slack"] = True
        rep.add(f"No slack bus marked, so the first bus ({buses[0]['id']}) is used as the source")
    elif len(slacks) > 1:
        rep.add(f"{len(slacks)} slack buses marked; reliability and short-circuit use the first one")

    # ---------------- lines ----------------
    l_headers, l_rows = _read_table(lines_path)
    lc = _resolve(l_headers, LINE_ALIASES)
    if lc["from"] is None or lc["to"] is None:
        raise ValueError("The lines file needs from-bus and to-bus columns "
                         "(for example from_bus/to_bus, from/to, fbus/tbus).")
    if lc["length"] is None:
        rep.add("lines file: no length column recognised, assuming 1 km for every line")
    if lc["r"] is None or lc["x"] is None:
        rep.add(f"lines file: R or X column not recognised, assuming {DEFAULT_R_X_OHM_PER_KM:g} ohm/km")
    if lc["rating"] is None:
        rep.add(f"lines file: no current-rating column recognised, assuming {DEFAULT_RATING_KA:g} kA")
    if lc["status"] is None:
        rep.add("lines file: no status column recognised, all lines treated as closed")

    len_scale, len_unit = _length_scale(lc["length"], u["length"])
    r_mode = _impedance_mode(lc["r"], u["impedance"])
    x_mode = _impedance_mode(lc["x"], u["impedance"])
    if lc["length"] and len_unit != u["length"]:
        rep.add(f"lines file: column '{lc['length']}' read as {len_unit} from its header")

    lines = []
    for i, r in enumerate(l_rows):
        f_id = _clean_id(r.get(lc["from"], ""))
        t_id = _clean_id(r.get(lc["to"], ""))
        if not f_id or not t_id:
            rep.agg("Line skipped: blank from/to bus", f"row {i + 2}")
            continue

        length = _safe_float(r.get(lc["length"])) if lc["length"] else None
        if length is None:
            length = 1.0
            if lc["length"]:
                rep.agg("Blank length replaced by 1 km", f"row {i + 2}")
        else:
            length *= len_scale
        if length <= 0:
            length = 0.001
            rep.agg("Zero or negative length raised to 0.001 km", f"row {i + 2}")

        rating = _safe_float(r.get(lc["rating"])) if lc["rating"] else None
        if rating is None or rating <= 0:
            if lc["rating"]:
                rep.agg(f"Blank or invalid rating replaced by {DEFAULT_RATING_KA:g} kA", f"row {i + 2}")
            rating = DEFAULT_RATING_KA
        elif rating > 10:
            rating /= 1000.0
            rep.agg("Rating above 10 read as amperes and converted to kA", f"row {i + 2}")

        status = _clean_id(r.get(lc["status"], "")).lower() if lc["status"] else ""
        in_service = True
        if status in OPEN_WORDS:
            in_service = False
        elif status and status not in CLOSED_WORDS:
            rep.agg("Unrecognised status value treated as closed", status)

        sn = _safe_float(r.get(lc["sn"])) if lc["sn"] else None
        vk = _safe_float(r.get(lc["vk"])) if lc["vk"] else None
        vkr = _safe_float(r.get(lc["vkr"])) if lc["vkr"] else None
        lines.append({
            "id": r.get(lc["id"], "") if lc["id"] else "",
            "from": f_id, "to": t_id, "length": length,
            "r": _safe_float(r.get(lc["r"])) if lc["r"] else None,
            "x": _safe_float(r.get(lc["x"])) if lc["x"] else None,
            "rating": rating, "in_service": in_service,
            "sn": sn if (sn and sn > 0) else None,
            "vk": vk if (vk and vk > 0) else None,
            "vkr": vkr if (vkr is not None and vkr >= 0) else None,
            "row": i,
        })

    # ---------------- build pandapower net ----------------
    net = pp.create_empty_network(name="Zenithic Grid")
    bus_idx = {}
    customers = []
    for b in buses:
        idx = pp.create_bus(net, vn_kv=b["kv"], name=b["id"])
        bus_idx[b["id"]] = idx
        if b["slack"]:
            pp.create_ext_grid(net, bus=idx, vm_pu=1.0, name="Source",
                               s_sc_max_mva=5000.0, rx_max=0.1)
        if b["p"] != 0 or b["q"] != 0:
            pp.create_load(net, bus=idx, p_mw=b["p"], q_mvar=b["q"], name=f"Load_{b['id']}")
        if b["customers"] is not None:
            customers.append(max(0.0, b["customers"]))
        else:
            customers.append(1.0 if ((b["p"] != 0 or b["q"] != 0) and not b["slack"]) else 0.0)
    net.bus["gg_customers"] = customers
    if bc["customers"] is None:
        rep.add("No customer-count column: each non-source load bus counts as one customer")

    s_total = math.hypot(sum(abs(b["p"]) for b in buses), sum(abs(b["q"]) for b in buses))
    default_sn = max(1.0, 1.2 * s_total)

    for ln in lines:
        label = ln["id"] or f"L{ln['row']}"
        if ln["from"] not in bus_idx or ln["to"] not in bus_idx:
            rep.agg("Line skipped: bus not found in the buses file", f"{label} ({ln['from']} to {ln['to']})")
            continue
        if ln["from"] == ln["to"]:
            rep.agg("Line skipped: from and to bus are the same", label)
            continue

        f_bus, t_bus = bus_idx[ln["from"]], bus_idx[ln["to"]]
        v_from = float(net.bus.at[f_bus, "vn_kv"])
        v_to = float(net.bus.at[t_bus, "vn_kv"])

        if max(v_from, v_to) / min(v_from, v_to) > 1.1:
            hv, lv = (f_bus, t_bus) if v_from >= v_to else (t_bus, f_bus)
            vk = ln["vk"] or 6.0
            vkr = ln["vkr"] if ln["vkr"] is not None else 0.5
            vkr = min(vkr, vk * 0.99)
            pp.create_transformer_from_parameters(
                net, hv_bus=hv, lv_bus=lv,
                sn_mva=ln["sn"] or default_sn,
                vn_hv_kv=max(v_from, v_to), vn_lv_kv=min(v_from, v_to),
                vk_percent=vk, vkr_percent=vkr, pfe_kw=0, i0_percent=0,
                name=label, in_service=ln["in_service"])
            rep.agg("Branch between different voltage levels built as a transformer "
                    "(impedance and rating from file, otherwise 6% and 1.2 x total load)", label)
        else:
            z_base = v_from ** 2 / u["base_mva"]
            r_pk = _to_ohm_per_km(ln["r"], r_mode, ln["length"], z_base)
            x_pk = _to_ohm_per_km(ln["x"], x_mode, ln["length"], z_base)
            if r_pk < MIN_IMPEDANCE_OHM_PER_KM or x_pk < MIN_IMPEDANCE_OHM_PER_KM:
                rep.agg(f"Zero or negative R/X raised to {MIN_IMPEDANCE_OHM_PER_KM:g} ohm/km", label)
                r_pk = max(r_pk, MIN_IMPEDANCE_OHM_PER_KM)
                x_pk = max(x_pk, MIN_IMPEDANCE_OHM_PER_KM)
            pp.create_line_from_parameters(
                net, from_bus=f_bus, to_bus=t_bus, length_km=ln["length"],
                r_ohm_per_km=r_pk, x_ohm_per_km=x_pk, c_nf_per_km=0.0,
                max_i_ka=ln["rating"], name=label, in_service=ln["in_service"])

    open_count = int((~net.line.in_service).sum()) + int((~net.trafo.in_service).sum())
    if open_count:
        rep.add(f"{open_count} open branch(es) (tie switches) kept out of service")

    if len(net.load) == 0:
        pp.create_load(net, bus=net.bus.index[-1], p_mw=0.001, q_mvar=0.0001, name="DummyLoad")
        rep.add("No loads found in the buses file; a tiny dummy load was added so the solver can run")

    net["gg_report"] = rep.finish()
    net["gg_units"] = u
    return net


# ---------------------------------------------------------------------------
# Solver used by every script
# ---------------------------------------------------------------------------
def run_robust_powerflow(net):
    """Try several solvers. Returns True on success; on failure the reasons
    are left in net["gg_pf_error"]."""
    tries = [
        dict(algorithm="nr", max_iteration=30),
        dict(algorithm="iwamoto_nr", max_iteration=50),
        dict(algorithm="nr", init="dc", max_iteration=50),
        dict(algorithm="bfsw", max_iteration=100),
    ]
    errors = []
    for kw in tries:
        try:
            pp.runpp(net, numba=False, **kw)
            net["gg_pf_error"] = ""
            net["gg_pf_algorithm"] = kw["algorithm"]
            return True
        except Exception as e:  # noqa: BLE001
            errors.append(f"{kw['algorithm']}: {type(e).__name__}")
    net["gg_pf_error"] = "; ".join(errors)
    return False