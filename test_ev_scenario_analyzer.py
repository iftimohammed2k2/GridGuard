import unittest

import pandapower.networks as pn

from ev_scenario_analyzer import (
    EV_CONNECTION_BUSES,
    add_ev_loads,
    analyze_scenario,
    compare_with_baseline,
    distribute_evs,
    run_analysis,
    validate_inputs,
)


class EVScenarioTests(unittest.TestCase):

    def test_zero_evs_distribution(self):
        result = distribute_evs(0, [18, 25, 30])
        self.assertEqual(result, {18: 0, 25: 0, 30: 0})

    def test_even_distribution(self):
        result = distribute_evs(12, [18, 25, 30])
        self.assertEqual(result, {18: 4, 25: 4, 30: 4})

    def test_remainder_distribution(self):
        result = distribute_evs(10, [18, 25, 30])
        self.assertEqual(result, {18: 4, 25: 3, 30: 3})

    def test_negative_ev_count_rejected(self):
        with self.assertRaises(ValueError):
            distribute_evs(-1, [18, 25, 30])

    def test_empty_buses_rejected_for_nonzero_evs(self):
        with self.assertRaises(ValueError):
            distribute_evs(1, [])

    def test_duplicate_buses_rejected(self):
        with self.assertRaises(ValueError):
            distribute_evs(5, [18, 18])

    def test_ev_loads_added_to_network(self):
        net = pn.case33bw()
        initial_load_count = len(net.load)

        add_ev_loads(
            net,
            10,
            [18, 25, 30],
            charger_kw=7.2,
            power_factor=0.98,
        )

        self.assertEqual(len(net.load), initial_load_count + 3)
        self.assertAlmostEqual(
            net.load["p_mw"].sum()
            - pn.case33bw().load["p_mw"].sum(),
            0.072,
            places=6,
        )

    def test_invalid_power_factor_rejected(self):
        net = pn.case33bw()

        with self.assertRaises(ValueError):
            validate_inputs(net, [0, 10], [18, 25], 7.2, 0)

    def test_unknown_bus_rejected(self):
        net = pn.case33bw()

        with self.assertRaises(ValueError):
            validate_inputs(net, [0, 10], [999], 7.2, 0.98)

    def test_scenario_power_flow_converges(self):
        result = analyze_scenario(pn.case33bw(), 0)

        self.assertTrue(result["converged"], result["error"])
        self.assertIsNotNone(result["min_voltage_pu"])
        self.assertIsNotNone(result["active_losses_mw"])

    def test_ev_scenario_reports_added_power(self):
        result = analyze_scenario(pn.case33bw(), 10)

        self.assertAlmostEqual(
            result["total_ev_power_mw"], 0.072, places=6
        )

    def test_baseline_comparison(self):
        results = run_analysis([0, 10], EV_CONNECTION_BUSES)

        self.assertEqual(
            [r["ev_count"] for r in results],
            [0, 10],
        )

        for result in results:
            self.assertIn("new_voltage_violation_bus_ids", result)
            self.assertIn("min_voltage_change_pu", result)

    def test_unrated_lines_are_not_claimed_assessable(self):
        result = analyze_scenario(pn.case33bw(), 0)

        self.assertTrue(result["converged"], result["error"])
        self.assertEqual(result["lines_assessed"], 0)
        self.assertGreater(result["lines_unassessable"], 0)

    def test_baseline_is_required_for_comparison(self):
        results = [
            {
                "ev_count": 10,
                "converged": True,
                "min_voltage_pu": 0.90,
                "voltage_violation_bus_ids": [30],
            }
        ]

        compared = compare_with_baseline(results)

        self.assertIsNone(compared[0]["min_voltage_change_pu"])
        self.assertEqual(
            compared[0]["new_voltage_violation_bus_ids"], []
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)