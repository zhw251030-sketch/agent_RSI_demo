"""Synthetic-only checks of the eight preregistered diagnostic representations.

No CSV, optimizer, model, or archived candidate is executed. The one exact
historical copy is exercised as a diagnostic source on synthetic values only.
"""

import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SYNTHETIC_EQUATION_CALLS = 0
EXPECTED_IDS = (
    "stress-original-7", "stress-direct-4", "bact-triple-14",
    "bact-square-14-drop0", "bact-square-14-drop1",
    "bact-square-14-drop2", "bact-square-14-drop3", "bact-square-15",
)


class CandidateTests(unittest.TestCase):
    def metadata(self):
        path = HERE / "candidates.json"
        self.assertTrue(path.is_file(), "eight diagnostic candidates are not implemented")
        return json.loads(path.read_text(encoding="utf-8"))

    def candidate(self, name):
        rows = self.metadata()["candidates"]
        row = next(item for item in rows if item["id"] == name)
        path = ROOT / row["source_path"]
        self.assertTrue(path.is_file(), f"missing source for {name}")
        spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return row, module.equation

    def evaluate(self, name, inputs, params):
        global SYNTHETIC_EQUATION_CALLS
        _, equation = self.candidate(name)
        SYNTHETIC_EQUATION_CALLS += 1
        with np.errstate(over="ignore", invalid="ignore"):
            return equation(*inputs, params)

    def test_all_eight_have_bound_sources_and_provenance(self):
        metadata = self.metadata()
        self.assertEqual(tuple(row["id"] for row in metadata["candidates"]), EXPECTED_IDS)
        for row in metadata["candidates"]:
            with self.subTest(candidate=row["id"]):
                source = ROOT / row["source_path"]
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), row["source_sha256"])
                for parent in row["parents"]:
                    self.assertEqual(hashlib.sha256((ROOT / parent["path"]).read_bytes()).hexdigest(), parent["sha256"])
                self.assertEqual(row["initialization"], "np.ones(n_params)")
                self.assertEqual(row["output_guard"], "np.nan_to_num(output, nan=0.0, posinf=1e6, neginf=-1e6)")
                self.assertEqual(row["input_normalization"], "float64_asarray_ravel_only_no_scaling")

    def test_stress_original_is_exact_archived_copy(self):
        row, _ = self.candidate("stress-original-7")
        self.assertEqual((ROOT / row["source_path"]).read_bytes(), (ROOT / row["parents"][0]["path"]).read_bytes())

    def test_stress_algebraic_mapping_and_ones_initial_predictions(self):
        inputs = (np.array([-2.0, -0.5, 0.0, 1.5, 3.0]), np.array([1.0, -2.0, 0.5, 2.0, -1.0]))
        # Original order is cross, square0, square1, scale0, scale1, gain, offset.
        # Direct order is offset, cross, square0, square1. Values derived by hand.
        pairs = [
            ([1, 1, 1, 1, 1, 1, 1], [1, 1, 1, 1]),
            ([2, -3, 4, 0.5, -2, 3, -1], [-1, -6, -2.25, 48]),
            ([3, 5, -2, 0, 7, -4, 9], [9, 0, 0, 392]),
        ]
        for original, direct in pairs:
            with self.subTest(original=original):
                np.testing.assert_allclose(
                    self.evaluate("stress-original-7", inputs, original),
                    self.evaluate("stress-direct-4", inputs, direct), rtol=1e-12, atol=1e-12)

    def test_stress_direct_coefficients_cover_independent_signs(self):
        inputs = (np.array([-2.0, 0.0, 3.0]), np.array([1.0, 2.0, -1.0]))
        # beta = [offset, cross, square0, square1]; hand-calculated values.
        got = self.evaluate("stress-direct-4", inputs, [2, -3, -5, 7])
        np.testing.assert_allclose(got, [-5, 30, -27], rtol=0, atol=0)

    def test_bact_one_hot_coefficients_have_declared_feature_order(self):
        # At (2,3,5,7): common basis is [1,2,3,5,7,6,10,14,15,21,35].
        common = [1, 2, 3, 5, 7, 6, 10, 14, 15, 21, 35]
        expected = {
            "bact-triple-14": common + [30, 42, 70],
            "bact-square-14-drop0": common + [9, 25, 49],
            "bact-square-14-drop1": common + [4, 25, 49],
            "bact-square-14-drop2": common + [4, 9, 49],
            "bact-square-14-drop3": common + [4, 9, 25],
            "bact-square-15": common + [4, 9, 25, 49],
        }
        for name, features in expected.items():
            row, _ = self.candidate(name)
            self.assertEqual(row["n_params"], len(features))
            self.assertEqual(len(row["feature_ids"]), len(features))
            for i, value in enumerate(features):
                with self.subTest(candidate=name, coefficient=i):
                    params = np.zeros(len(features))
                    params[i] = 1.0
                    got = self.evaluate(name, ([2.0], [3.0], [5.0], [7.0]), params)
                    np.testing.assert_array_equal(got, [float(value)])

    def test_bact_square_drop_is_nested_at_zero_coefficient(self):
        inputs = (np.array([-2.0, 0.5]), np.array([3.0, -1.0]), np.array([0.0, 2.0]), np.array([5.0, -3.0]))
        for drop in range(4):
            full = np.arange(1.0, 16.0)
            full[11 + drop] = 0.0
            smaller = np.delete(full, 11 + drop)
            np.testing.assert_allclose(
                self.evaluate(f"bact-square-14-drop{drop}", inputs, smaller),
                self.evaluate("bact-square-15", inputs, full), rtol=1e-12, atol=1e-12)

    def test_all_sources_flatten_inputs_and_preserve_batch_shape(self):
        for name in EXPECTED_IDS:
            row, _ = self.candidate(name)
            count = 2 if name.startswith("stress") else 4
            inputs = tuple(np.array([[1.0, -1.0], [0.5, 2.0]]) for _ in range(count))
            got = self.evaluate(name, inputs, np.ones(row["n_params"]))
            self.assertEqual(got.shape, (4,))
            self.assertTrue(np.isfinite(got).all())

    def test_all_output_guards_replace_nonfinite_values_without_finite_clipping(self):
        for name in EXPECTED_IDS:
            row, _ = self.candidate(name)
            count = 2 if name.startswith("stress") else 4
            inputs = tuple(np.array([1.0]) for _ in range(count))
            for coefficient, expected in [(float("nan"), 0.0), (float("inf"), 1e6), (-float("inf"), -1e6), (2e6, 2e6)]:
                params = np.zeros(row["n_params"])
                # Change only offset; original stress needs finite multiplicative terms.
                params[6 if name == "stress-original-7" else 0] = coefficient
                got = self.evaluate(name, inputs, params)
                np.testing.assert_array_equal(got, [expected])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CandidateTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({"synthetic_equation_calls": SYNTHETIC_EQUATION_CALLS,
                      "tests_run": result.testsRun, "failures": len(result.failures),
                      "errors": len(result.errors), "real_csv_reads": 0, "fits": 0}, sort_keys=True))
    raise SystemExit(not result.wasSuccessful())
