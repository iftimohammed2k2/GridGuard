import argparse, csv, json, math
from pathlib import Path
import pandapower as pp
import pandapower.networks as pn

BASE_DIR=Path(__file__).resolve().parent
REPORT_FILE=BASE_DIR/"thermal_report.txt"
SUMMARY_FILE=BASE_DIR/"thermal_summary.json"
RESULTS_FILE=BASE_DIR/"thermal_results.csv"
MAX_LOADING_PERCENT=100.0
MAX_PLAUSIBLE_LINE_RATING_KA=1000.0
POWERFLOW_OPTIONS={"algorithm":"nr","numba":False,"init":"auto","max_iteration":30}

def finite_positive(value):
    try:
        n=float(value); return math.isfinite(n) and n>0
    except (TypeError,ValueError,OverflowError): return False

def valid_integer_count(value):
    try:
        n=float(value); return math.isfinite(n) and n>=1 and n.is_integer()
    except (TypeError,ValueError,OverflowError): return False

def finite_nonnegative(value):
    try:
        n=float(value); return n if math.isfinite(n) and n>=0 else None
    except (TypeError,ValueError,OverflowError): return None

def finite_number_or_none(value):
    try:
        n=float(value); return n if math.isfinite(n) else None
    except (TypeError,ValueError,OverflowError): return None

def classify_loading(loading_percent,rating_valid,threshold=MAX_LOADING_PERCENT):
    if not rating_valid or loading_percent is None: return "NOT ASSESSABLE"
    try: loading,limit=float(loading_percent),float(threshold)
    except (TypeError,ValueError,OverflowError): return "NOT ASSESSABLE"
    if not math.isfinite(loading) or not math.isfinite(limit) or loading<0 or limit<=0: return "NOT ASSESSABLE"
    return "OVERLOAD" if loading>limit else "PASS"

def is_in_service(value):
    if value is None: return True
    if isinstance(value,str): return value.strip().lower() not in {"false","0","no","off",""}
    try:
        if isinstance(value,float) and math.isnan(value): return True
        return bool(value)
    except (TypeError,ValueError): return True

def load_line_ratings_csv(path,net):
    """CSV columns: equipment_id,rating_ka. Optional equipment_type must be line."""
    with Path(path).open("r",newline="",encoding="utf-8-sig") as f:
        reader=csv.DictReader(f)
        if not reader.fieldnames: raise ValueError("Ratings CSV is empty or has no header.")
        headers={h.strip() for h in reader.fieldnames if h}
        missing={"equipment_id","rating_ka"}-headers
        if missing: raise ValueError("Ratings CSV missing required column(s): "+", ".join(sorted(missing)))
        ratings={}; errors=[]
        for row_num,row in enumerate(reader,start=2):
            row={str(k).strip():(v.strip() if isinstance(v,str) else v) for k,v in row.items() if k is not None}
            kind=row.get("equipment_type","line").strip().lower()
            if kind and kind!="line":
                errors.append(f"Row {row_num}: equipment_type must be 'line'."); continue
            try:
                raw=float(row.get("equipment_id",""))
                if not math.isfinite(raw) or not raw.is_integer(): raise ValueError
                eid=int(raw)
            except (TypeError,ValueError,OverflowError):
                errors.append(f"Row {row_num}: equipment_id must be an integer."); continue
            if eid not in net.line.index:
                errors.append(f"Row {row_num}: line ID {eid} does not exist in this network."); continue
            if eid in ratings:
                errors.append(f"Row {row_num}: duplicate rating for line ID {eid}."); continue
            raw_rating=row.get("rating_ka")
            if not finite_positive(raw_rating):
                errors.append(f"Row {row_num}: rating_ka must be a finite positive number."); continue
            rating=float(raw_rating)
            if rating>=MAX_PLAUSIBLE_LINE_RATING_KA:
                errors.append(f"Row {row_num}: rating_ka for line ID {eid} exceeds the software sanity guard."); continue
            ratings[eid]=rating
    if errors: raise ValueError("Ratings CSV validation failed:\n- "+"\n- ".join(errors))
    in_service={int(i) for i,r in net.line.iterrows() if is_in_service(r.get("in_service",True))}
    missing_ids=sorted(in_service-set(ratings))
    if missing_ids: raise ValueError("Ratings CSV is missing ratings for in-service line ID(s): "+", ".join(map(str,missing_ids)))
    return ratings

def apply_line_ratings(net,ratings):
    for eid,rating in ratings.items():
        if eid not in net.line.index or not finite_positive(rating): raise ValueError(f"Invalid rating mapping for line ID {eid}.")
    for eid,rating in ratings.items(): net.line.at[eid,"max_i_ka"]=float(rating)

def assess_equipment(net,element_type,result_table,threshold=MAX_LOADING_PERCENT):
    if element_type=="line": table,col,unit=net.line,"max_i_ka","kA"
    elif element_type=="trafo": table,col,unit=net.trafo,"sn_mva","MVA"
    else: raise ValueError(f"Unsupported equipment type: {element_type}")
    records=[]
    for eid,item in table.iterrows():
        if not is_in_service(item.get("in_service",True)): continue
        supplied=finite_number_or_none(item.get(col)); df=finite_number_or_none(item.get("df",1.0)); parallel=finite_number_or_none(item.get("parallel",1))
        r={"equipment_type":element_type,"equipment_id":int(eid),"rating_column":col,"supplied_rating":supplied,"rating_unit":unit,"derating_factor":df,"parallel_count":parallel,"effective_rating":None,"current_ka":None,"loading_percent":None,"rating_valid":False,"status":"NOT ASSESSABLE","rating_note":""}
        if result_table is None or eid not in result_table.index:
            r["rating_note"]="Missing power-flow result for equipment."; records.append(r); continue
        reasons=[]
        if not finite_positive(item.get(col)): reasons.append(f"Invalid {col} rating.")
        elif element_type=="line" and float(item.get(col))>=MAX_PLAUSIBLE_LINE_RATING_KA: reasons.append("Rating is at or above software sanity guard; verify authoritative asset data.")
        raw_df=item.get("df",1.0); raw_parallel=item.get("parallel",1)
        if not finite_positive(raw_df): reasons.append("Invalid derating factor df; expected finite value > 0.")
        elif float(raw_df)>1: reasons.append("Derating factor df exceeds 1.0; verify source data.")
        if not valid_integer_count(raw_parallel): reasons.append("Parallel equipment count must be a positive integer.")
        effective=None
        if not reasons:
            effective=float(item.get(col))*float(raw_df)*int(float(raw_parallel))
            if not finite_positive(effective): reasons.append("Calculated effective rating is invalid."); effective=None
        valid=not reasons and effective is not None
        r["rating_valid"],r["effective_rating"]=valid,effective
        r["rating_note"]=(f"Rating inputs passed software checks. Effective rating: {effective:.6g} {unit}. This is not independent verification of the asset rating." if valid else " ".join(reasons))
        if element_type=="line":
            r["current_ka"]=finite_nonnegative(result_table.loc[eid].get("i_ka"))
            loading=r["current_ka"]/effective*100 if valid and r["current_ka"] is not None else None
        else: loading=finite_nonnegative(result_table.loc[eid].get("loading_percent")) if valid else None
        if loading is not None and not math.isfinite(loading): loading=None
        r["loading_percent"]=loading; r["status"]=classify_loading(loading,valid,threshold); records.append(r)
    return records

def run_thermal_check(net,threshold=MAX_LOADING_PERCENT):
    s={"status":"FAIL","powerflow_converged":False,"converged":False,"lines_assessed":0,"line_count":0,"transformers_assessed":0,"equipment_assessed":0,"equipment_pass":0,"equipment_overloaded":0,"equipment_not_assessable":0,"unassessable_count":0,"threshold_percent":threshold,"errors":[],"equipment":[]}
    if not finite_positive(threshold) or float(threshold)>1000: s["errors"].append("Invalid thermal loading threshold."); return s
    s["threshold_percent"]=float(threshold)
    try:
        pp.runpp(net,**POWERFLOW_OPTIONS)
        if not bool(net.converged): s["errors"].append("Power flow did not converge."); return s
        s["powerflow_converged"]=s["converged"]=True
    except Exception as exc: s["errors"].append(f"Power-flow calculation failed: {type(exc).__name__}: {exc}"); return s
    try: records=assess_equipment(net,"line",net.res_line,float(threshold))+assess_equipment(net,"trafo",net.res_trafo,float(threshold))
    except Exception as exc: s["errors"].append(f"Equipment assessment failed: {type(exc).__name__}: {exc}"); return s
    s["equipment"]=records
    s["lines_assessed"]=s["line_count"]=sum(r["equipment_type"]=="line" for r in records)
    s["transformers_assessed"]=sum(r["equipment_type"]=="trafo" for r in records); s["equipment_assessed"]=len(records)
    s["equipment_pass"]=sum(r["status"]=="PASS" for r in records)
    s["equipment_overloaded"]=sum(r["status"]=="OVERLOAD" for r in records)
    s["equipment_not_assessable"]=sum(r["status"]=="NOT ASSESSABLE" for r in records); s["unassessable_count"]=s["equipment_not_assessable"]
    s["status"]="REVIEW" if s["equipment_overloaded"] else ("INCOMPLETE" if s["equipment_not_assessable"] else "PASS")
    return s

def save_report(s):
    equipment=s.get("equipment",[])
    lines=["="*76,"GRIDGUARD — THERMAL LOADING REPORT","="*76,"",f"Assessment status: {s.get('status','FAIL')}",f"Power flow converged: {s.get('powerflow_converged',False)}",f"Thermal loading threshold: {s.get('threshold_percent',MAX_LOADING_PERCENT)}%",f"Lines assessed: {s.get('lines_assessed',0)}",f"Transformers assessed: {s.get('transformers_assessed',0)}",f"Equipment PASS: {s.get('equipment_pass',0)}",f"Equipment OVERLOAD: {s.get('equipment_overloaded',0)}",f"Equipment NOT ASSESSABLE: {s.get('equipment_not_assessable',0)}","","EQUIPMENT DETAILS",""]
    for r in equipment:
        lines += [f"{r['equipment_type'].upper()} ID {r['equipment_id']}",f"  Supplied rating: {r['supplied_rating']} {r['rating_unit']}",f"  Effective rating: {r['effective_rating']} {r['rating_unit']}",f"  Current: {r['current_ka']} kA",f"  Loading: {r['loading_percent']}%",f"  Status: {r['status']}",f"  Note: {r['rating_note']}",""]
    lines += ["ENGINEERING LIMITATIONS","This is a software screening result, not certification of network safety.","A rating passing software checks is not proof the asset rating is correct.","Use documented asset data for engineering decisions."]
    REPORT_FILE.write_text("\n".join(lines),encoding="utf-8")
    SUMMARY_FILE.write_text(json.dumps(s,indent=2,allow_nan=False),encoding="utf-8")
    fields=["equipment_type","equipment_id","rating_column","supplied_rating","rating_unit","derating_factor","parallel_count","effective_rating","current_ka","loading_percent","rating_valid","status","rating_note"]
    with RESULTS_FILE.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader()
        for r in equipment: w.writerow({k:r.get(k) for k in fields})

def main(argv=None):
    parser=argparse.ArgumentParser(description="GridGuard thermal loading checker")
    parser.add_argument("--ratings-csv",help="CSV with equipment_id,rating_ka for every in-service line")
    parser.add_argument("--demo-rating-ka",type=float,default=0.25,help="Assumed rating for DEMO ONLY (default 0.25 kA)")
    parser.add_argument("--no-demo-ratings",action="store_true",help="Leave benchmark placeholder ratings unchanged")
    args=parser.parse_args(argv)
    try:
        net=pn.case33bw()
        if args.ratings_csv:
            ratings=load_line_ratings_csv(args.ratings_csv,net); apply_line_ratings(net,ratings)
            print(f"Rating source: customer CSV ({args.ratings_csv})")
        elif not args.no_demo_ratings:
            if not finite_positive(args.demo_rating_ka) or args.demo_rating_ka>=MAX_PLAUSIBLE_LINE_RATING_KA: raise ValueError("Demo rating must be positive and below sanity guard.")
            net.line["max_i_ka"]=args.demo_rating_ka
            print(f"DEMO ONLY: assumed rating {args.demo_rating_ka} kA; not verified asset data.")
        else: print("No ratings override; benchmark placeholder ratings remain.")
        s=run_thermal_check(net); save_report(s)
    except Exception as exc: print(f"ERROR: {type(exc).__name__}: {exc}"); return 1
    print(f"Assessment status: {s['status']}\nPower flow converged: {s['powerflow_converged']}\nLines assessed: {s['lines_assessed']}\nTransformers assessed: {s['transformers_assessed']}\nPASS: {s['equipment_pass']}\nOVERLOAD: {s['equipment_overloaded']}\nNOT ASSESSABLE: {s['equipment_not_assessable']}\n\nText report: {REPORT_FILE}\nJSON summary: {SUMMARY_FILE}\nCSV results: {RESULTS_FILE}")
    return 0

if __name__=="__main__": raise SystemExit(main())