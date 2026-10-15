import csv, tempfile, unittest
from pathlib import Path
import pandapower.networks as pn
from thermal_loading_checker import classify_loading, finite_positive, load_line_ratings_csv, apply_line_ratings, run_thermal_check, MAX_PLAUSIBLE_LINE_RATING_KA

class ThermalLoadingTests(unittest.TestCase):
    def test_loading_below_limit_passes(self): self.assertEqual(classify_loading(75,True),"PASS")
    def test_loading_at_limit_passes(self): self.assertEqual(classify_loading(100,True),"PASS")
    def test_loading_above_limit_is_overload(self): self.assertEqual(classify_loading(100.1,True),"OVERLOAD")
    def test_missing_rating_is_not_assessable(self): self.assertEqual(classify_loading(0,False),"NOT ASSESSABLE")
    def test_missing_loading_is_not_assessable(self): self.assertEqual(classify_loading(None,True),"NOT ASSESSABLE")
    def test_nan_loading_is_not_assessable(self): self.assertEqual(classify_loading(float("nan"),True),"NOT ASSESSABLE")
    def test_custom_threshold(self): self.assertEqual(classify_loading(85,True,80),"OVERLOAD")
    def test_placeholder_rating_exceeds_sanity_limit(self):
        self.assertTrue(finite_positive(99999)); self.assertGreaterEqual(99999,MAX_PLAUSIBLE_LINE_RATING_KA)
    def test_ieee_33_bus_power_flow_converges(self):
        r=run_thermal_check(pn.case33bw()); self.assertTrue(r["converged"],r["errors"]); self.assertEqual(r["line_count"],32)
    def test_invalid_ratings_never_pass(self):
        r=run_thermal_check(pn.case33bw()); self.assertTrue(r["converged"],r["errors"])
        for item in r["equipment"]:
            if not item["rating_valid"]: self.assertEqual(item["status"],"NOT ASSESSABLE")
    def test_benchmark_status_is_incomplete(self):
        r=run_thermal_check(pn.case33bw()); self.assertEqual(r["status"],"INCOMPLETE"); self.assertGreater(r["unassessable_count"],0)
    def make_csv(self, rows):
        f=tempfile.NamedTemporaryFile("w",newline="",suffix=".csv",delete=False,encoding="utf-8")
        with f:
            w=csv.DictWriter(f,fieldnames=["equipment_id","rating_ka"]); w.writeheader(); w.writerows(rows)
        self.addCleanup(lambda: Path(f.name).unlink(missing_ok=True)); return f.name
    def all_rows(self,net): return [{"equipment_id":int(i),"rating_ka":"0.25"} for i,r in net.line.iterrows() if bool(r.get("in_service",True))]
    def test_csv_import_matches_lines(self):
        net=pn.case33bw(); ratings=load_line_ratings_csv(self.make_csv(self.all_rows(net)),net); apply_line_ratings(net,ratings)
        self.assertEqual(len(ratings),32); self.assertAlmostEqual(float(net.line.at[0,"max_i_ka"]),.25)
    def test_csv_missing_rating_rejected(self):
        with self.assertRaisesRegex(ValueError,"missing ratings"): load_line_ratings_csv(self.make_csv([{"equipment_id":0,"rating_ka":".25"}]),pn.case33bw())
    def test_csv_duplicate_id_rejected(self):
        net=pn.case33bw(); rows=self.all_rows(net)+[{"equipment_id":0,"rating_ka":".3"}]
        with self.assertRaisesRegex(ValueError,"duplicate"): load_line_ratings_csv(self.make_csv(rows),net)
    def test_csv_invalid_rating_rejected(self):
        net=pn.case33bw(); rows=self.all_rows(net); rows[0]["rating_ka"]="0"
        with self.assertRaisesRegex(ValueError,"finite positive"): load_line_ratings_csv(self.make_csv(rows),net)
    def test_csv_unknown_id_rejected(self):
        net=pn.case33bw(); rows=self.all_rows(net); rows[0]["equipment_id"]=9999
        with self.assertRaisesRegex(ValueError,"does not exist"): load_line_ratings_csv(self.make_csv(rows),net)

if __name__=="__main__": unittest.main(verbosity=2)