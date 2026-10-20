"""Synthetic aggregate-only residual diagnostics; no benchmark data access."""
import json
import math
import unittest

from rsi_eval.symbolic_diagnostics import summarize_residuals


class SymbolicDiagnosticsTests(unittest.TestCase):
    def assert_error(self, X, y, predictions, names, reason=None):
        result = summarize_residuals(X, y, predictions, names)
        self.assertEqual(result["status"], "error", result)
        self.assertEqual(result["scope"], "train")
        if reason is not None:
            self.assertEqual(result["error"], reason)
        self.assertEqual(set(result), {"status", "scope", "residual_definition", "error"})
        json.dumps(result, allow_nan=False)

    def test_exact_small_example_uses_prediction_minus_target(self):
        result = summarize_residuals([[0], [1], [2], [3]],
                                     [1, 3, 5, 7], [2, 1, 8, 7], ["x"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["scope"], "train")
        self.assertEqual(result["residual_definition"], "prediction - target")
        self.assertEqual(result["n"], 4)
        self.assertEqual(result["bias"], 0.5)
        self.assertAlmostEqual(result["rmse"], math.sqrt(3.5))
        self.assertAlmostEqual(result["standardized_bias"], 0.5 / math.sqrt(5))
        self.assertIsNone(result["standardized_bias_reason"])
        variable = result["inputs"][0]
        self.assertEqual(variable["name"], "x")
        self.assertEqual(variable["boundaries"], [0, 0.75, 1.5, 2.25, 3])
        self.assertEqual([item["count"] for item in variable["bins"]], [1, 1, 1, 1])
        self.assertEqual([item["mean_residual"] for item in variable["bins"]], [1, -2, 3, 0])
        self.assertEqual([item["rmse"] for item in variable["bins"]], [1, 2, 3, 0])
        self.assertEqual([item["upper_inclusive"] for item in variable["bins"]],
                         [False, False, False, True])
        self.assertEqual([(item["lower"], item["upper"]) for item in variable["bins"]],
                         [(0, 0.75), (0.75, 1.5), (1.5, 2.25), (2.25, 3)])
        json.dumps(result, allow_nan=False)

    def test_boundaries_and_membership_depend_only_on_inputs(self):
        X = [[7, 8], [0, 7], [1, 4], [1, 9], [3, 0]]
        first = summarize_residuals(X, [0, 1, 2, 3, 4], [1, 0, 1, 0, 1], ["x", "v"])
        second = summarize_residuals(X, [8, 6, 4, 2, 0], [100, -1, -3, 0, 7], ["x", "v"])
        for left, right in zip(first["inputs"], second["inputs"]):
            self.assertEqual(left["boundaries"], right["boundaries"])
            self.assertEqual([b["count"] for b in left["bins"]],
                             [b["count"] for b in right["bins"]])
        self.assertEqual(first["inputs"][0]["boundaries"], [0, 1, 1, 3, 7])
        self.assertEqual([b["count"] for b in first["inputs"][0]["bins"]], [1, 0, 2, 2])
        self.assertEqual(first["inputs"][1]["boundaries"], [0, 4, 7, 8, 9])

    def test_constant_input_keeps_ties_together_and_marks_empty_bins(self):
        result = summarize_residuals([[4], [4], [4], [4]], [0, 1, 2, 3], [1, 0, 5, 4], ["x"])
        variable = result["inputs"][0]
        self.assertEqual(variable["boundaries"], [4, 4, 4, 4, 4])
        self.assertEqual([b["count"] for b in variable["bins"]], [0, 0, 0, 4])
        for item in variable["bins"][:3]:
            self.assertIsNone(item["mean_residual"])
            self.assertIsNone(item["rmse"])
        self.assertEqual(variable["bins"][3]["mean_residual"], 1)
        self.assertAlmostEqual(variable["bins"][3]["rmse"], math.sqrt(3))

    def test_constant_target_marks_undefined_standardized_bias(self):
        result = summarize_residuals([[0], [1]], [2, 2], [3, 5], ["x"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["bias"], 2)
        self.assertAlmostEqual(result["rmse"], math.sqrt(5))
        self.assertIsNone(result["standardized_bias"])
        self.assertEqual(result["standardized_bias_reason"], "zero_target_variance")
        json.dumps(result, allow_nan=False)

    def test_single_row_is_valid_with_three_empty_bins(self):
        result = summarize_residuals(((2,),), (3,), (5,), ("x",))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["bias"], 2)
        self.assertEqual(result["rmse"], 2)
        self.assertIsNone(result["standardized_bias"])
        self.assertEqual([b["count"] for b in result["inputs"][0]["bins"]], [0, 0, 0, 1])

    def test_constant_fractional_target_is_not_given_spurious_variance(self):
        result = summarize_residuals([[0]] * 11, [0.1] * 11, [0.2] * 11, ["x"])
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["standardized_bias"])
        self.assertEqual(result["standardized_bias_reason"], "zero_target_variance")

    def test_underflowed_target_variance_is_distinguished_from_constant_target(self):
        result = summarize_residuals([[0], [1]], [-1e-200, 1e-200], [1, 2], ["x"])
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["standardized_bias"])
        self.assertEqual(result["standardized_bias_reason"], "target_variance_underflow")

    def test_rejects_empty_misaligned_ragged_or_nonsequence_shapes(self):
        cases = [([], [], [], ["x"]),
                 ([[1], [2]], [1], [1, 2], ["x"]),
                 ([[1], [2]], [1, 2], [1], ["x"]),
                 ([[1], [2, 3]], [1, 2], [1, 2], ["x"]),
                 ([1, 2], [1, 2], [1, 2], ["x"]),
                 ([[1], [2]], "12", [1, 2], ["x"]),
                 ([[1], [2]], [1, 2], iter([1, 2]), ["x"]),
                 (None, [1], [1], ["x"])]
        for case in cases:
            with self.subTest(case=case):
                self.assert_error(*case)

    def test_rejects_strings_booleans_complex_and_nested_numeric_cells(self):
        for invalid in ["2", True, False, 2j, [2], None, {}]:
            for location in ["X", "y", "predictions"]:
                values = {"X": [[1], [2]], "y": [1, 2], "predictions": [1, 2]}
                if location == "X":
                    values["X"][0][0] = invalid
                else:
                    values[location][0] = invalid
                with self.subTest(invalid=invalid, location=location):
                    self.assert_error(values["X"], values["y"], values["predictions"], ["x"])

    def test_rejects_all_nonfinite_inputs_without_json_nan(self):
        for invalid in [float("nan"), float("inf"), -float("inf")]:
            for location in ["X", "y", "predictions"]:
                values = {"X": [[1], [2]], "y": [1, 2], "predictions": [1, 2]}
                if location == "X":
                    values["X"][0][0] = invalid
                else:
                    values[location][0] = invalid
                with self.subTest(invalid=invalid, location=location):
                    self.assert_error(values["X"], values["y"], values["predictions"], ["x"])

    def test_rejects_numeric_conversion_residual_and_squared_overflow(self):
        cases = [([[1]], [0], [10 ** 1000], ["x"]),
                 ([[10 ** 1000]], [0], [0], ["x"]),
                 ([[1]], [-1e308], [1e308], ["x"]),
                 ([[1], [2]], [0, 1], [1e200, 1e200], ["x"]),
                 ([[1], [2]], [-1e200, 1e200], [-1e200, 1e200], ["x"])]
        for case in cases:
            with self.subTest(case=case):
                self.assert_error(*case, reason="numeric_overflow")

    def test_extreme_finite_input_boundaries_do_not_overflow_interpolation(self):
        result = summarize_residuals([[-1e308], [1e308]], [0, 1], [0, 1], ["x"])
        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(result["inputs"][0]["boundaries"], [-1e308, -5e307, 0, 5e307, 1e308])
        json.dumps(result, allow_nan=False)

    def test_rejects_missing_duplicate_unbounded_or_mismatched_input_names(self):
        for names in [[], ["x", "v"], [""], ["x" * 65], [True], "x", ["x\ny"]]:
            with self.subTest(names=names):
                self.assert_error([[0], [1]], [0, 1], [0, 1], names)
        self.assert_error([[0, 0], [1, 1]], [0, 1], [0, 1], ["x", "x"])

    def test_rejects_more_than_three_inputs_or_one_hundred_thousand_rows(self):
        self.assert_error([[0, 0, 0, 0]], [0], [0], ["a", "b", "c", "d"])
        self.assert_error([[0]] * 100001, [0] * 100001, [0] * 100001, ["x"],
                          reason="row_limit_exceeded")

    def test_output_is_bounded_aggregates_without_sample_arrays(self):
        X = [[i, i % 3, 7] for i in range(10000)]
        result = summarize_residuals(X, list(range(10000)), [0] * 10000, ["x", "v", "t"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["n"], 10000)
        self.assertEqual(len(result["inputs"]), 3)
        self.assertLess(len(json.dumps(result, allow_nan=False)), 6000)
        forbidden = {"X", "y", "predictions", "residuals", "rows", "samples", "targets"}

        def check_tree(value):
            if isinstance(value, dict):
                self.assertTrue(forbidden.isdisjoint(value))
                for child in value.values():
                    check_tree(child)
            elif isinstance(value, list):
                self.assertLessEqual(len(value), 5)
                for child in value:
                    check_tree(child)

        check_tree(result)
        for variable in result["inputs"]:
            self.assertEqual(len(variable["bins"]), 4)
            self.assertEqual(sum(item["count"] for item in variable["bins"]), 10000)


if __name__ == "__main__":
    unittest.main()
