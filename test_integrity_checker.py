import csv
import tempfile
import unittest
from pathlib import Path

from integrity_checker import validate_network


BUS_HEADER = ["id", "nominal_kv"]
LINE_HEADER = [
    "id", "from_bus", "to_bus",
    "length_km", "r_ohm_per_km", "x_ohm_per_km",
]


class IntegrityCheckerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.buses = self.root / "buses.csv"
        self.lines = self.root / "lines.csv"
        self.write_valid_network()

    def tearDown(self):
        self.temp.cleanup()

    def write_csv(self, path, header, rows):
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(header)
            writer.writerows(rows)

    def write_valid_network(self):
        self.write_csv(self.buses, BUS_HEADER, [
            ["B1", "11"],
            ["B2", "11"],
            ["B3", "11"],
        ])
        self.write_csv(self.lines, LINE_HEADER, [
            ["L1", "B1", "B2", "1.0", "0.30", "0.35"],
            ["L2", "B2", "B3", "0.5", "0.25", "0.30"],
        ])

    def check(self):
        return validate_network(self.buses, self.lines)

    def test_valid_network_passes(self):
        self.assertEqual(self.check()["status"], "PASS")

    def test_duplicate_bus_id_fails(self):
        self.write_csv(self.buses, BUS_HEADER, [
            ["B1", "11"], ["B1", "11"],
        ])
        self.assertEqual(self.check()["status"], "FAIL")

    def test_missing_bus_reference_fails(self):
        self.write_csv(self.lines, LINE_HEADER, [
            ["L1", "B1", "B99", "1", "0.3", "0.3"],
        ])
        self.assertEqual(self.check()["status"], "FAIL")

    def test_duplicate_line_id_fails(self):
        self.write_csv(self.lines, LINE_HEADER, [
            ["L1", "B1", "B2", "1", "0.3", "0.3"],
            ["L1", "B2", "B3", "1", "0.3", "0.3"],
        ])
        self.assertEqual(self.check()["status"], "FAIL")

    def test_zero_nominal_voltage_fails(self):
        self.write_csv(self.buses, BUS_HEADER, [
            ["B1", "0"], ["B2", "11"],
        ])
        self.write_csv(self.lines, LINE_HEADER, [
            ["L1", "B1", "B2", "1", "0.3", "0.3"],
        ])
        self.assertEqual(self.check()["status"], "FAIL")

    def test_non_numeric_resistance_fails(self):
        self.write_csv(self.lines, LINE_HEADER, [
            ["L1", "B1", "B2", "1", "abc", "0.3"],
        ])
        self.assertEqual(self.check()["status"], "FAIL")

    def test_negative_line_length_fails(self):
        self.write_csv(self.lines, LINE_HEADER, [
            ["L1", "B1", "B2", "-1", "0.3", "0.3"],
        ])
        self.assertEqual(self.check()["status"], "FAIL")

    def test_self_loop_fails(self):
        self.write_csv(self.lines, LINE_HEADER, [
            ["L1", "B1", "B1", "1", "0.3", "0.3"],
        ])
        self.assertEqual(self.check()["status"], "FAIL")

    def test_missing_required_column_fails(self):
        self.write_csv(
            self.buses,
            ["id"],
            [["B1"], ["B2"]],
        )
        self.assertEqual(self.check()["status"], "FAIL")

    def test_disconnected_network_is_review(self):
        self.write_csv(self.buses, BUS_HEADER, [
            ["B1", "11"], ["B2", "11"], ["B3", "11"],
        ])
        self.write_csv(self.lines, LINE_HEADER, [
            ["L1", "B1", "B2", "1", "0.3", "0.3"],
        ])
        self.assertEqual(self.check()["status"], "REVIEW")

    def test_missing_file_fails(self):
        self.lines.unlink()
        self.assertEqual(self.check()["status"], "FAIL")

    def test_malformed_csv_fails(self):
        self.lines.write_text(
            'id,from_bus,to_bus,length_km,r_ohm_per_km,x_ohm_per_km\n'
            'L1,"B1,B2,1,0.3,0.3\n',
            encoding="utf-8",
        )
        self.assertEqual(self.check()["status"], "FAIL")


if __name__ == "__main__":
    unittest.main(verbosity=2)