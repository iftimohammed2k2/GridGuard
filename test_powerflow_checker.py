import unittest

import pandapower.networks as pn

from powerflow_checker import analyze_network


class BaselinePowerFlowTests(unittest.TestCase):
    def test_ieee_33_bus_case_converges(self):
        result = analyze_network(pn.case33bw())
        self.assertTrue(result["converged"], result["errors"])
        self.assertEqual(result["summary"]["bus_count"], 33)

    def test_voltage_results_are_finite(self):
        result = analyze_network(pn.case33bw())
        self.assertTrue(result["converged"], result["errors"])

        values = result["bus_results"]["vm_pu"]
        self.assertFalse(values.isna().any())
        self.assertTrue(all(float(v) > 0 for v in values))

    def test_low_voltage_screening_runs(self):
        result = analyze_network(pn.case33bw())
        self.assertTrue(result["converged"], result["errors"])
        self.assertGreaterEqual(
            result["summary"]["low_voltage_bus_count"], 0
        )

    def test_no_external_grid_fails_safely(self):
        net = pn.case33bw()
        net.ext_grid.loc[:, "in_service"] = False

        result = analyze_network(net)
        self.assertFalse(result["converged"])
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["errors"])

    def test_thermal_rating_is_not_misrepresented(self):
        result = analyze_network(pn.case33bw())
        self.assertTrue(result["converged"], result["errors"])
        self.assertFalse(result["summary"]["line_loading_assessed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)