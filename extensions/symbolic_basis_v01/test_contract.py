"""Contract tests; generated equations see synthetic arrays only, never data files."""

import ast
import copy
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import unittest

import numpy as np


HERE = Path(__file__).resolve().parent
SYNTHETIC_EQUATION_CALLS = 0


class ContractTests(unittest.TestCase):
    def api(self):
        path = HERE / "contract.py"
        self.assertTrue(path.is_file(), "basis contract is not implemented")
        spec = importlib.util.spec_from_file_location("basis_contract_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def payload(self, features=None, explanation="Synthetic fixture, not a scientific result."):
        return {"feature_ids": features or ["m_0_0", "m_1_0", "m_0_1"], "explanation": explanation}

    def compile(self, features=None, n_inputs=2, explanation="Synthetic fixture"):
        features = features or ["m_0_0", "m_1_0", "m_0_1"]
        api = self.api()
        return api.compile_submission(self.payload(features, explanation), api.make_spec(n_inputs, len(features)))

    def equation(self, compiled):
        namespace = {"np": np}
        exec(compile(compiled["source"], "<generated synthetic candidate>", "exec"), namespace)
        return namespace["equation"]

    def evaluate(self, compiled, *args):
        global SYNTHETIC_EQUATION_CALLS
        SYNTHETIC_EQUATION_CALLS += 1
        return self.equation(compiled)(*args)

    def test_catalog_is_exhaustive_unique_graded_lex(self):
        api = self.api()
        catalog = json.loads((HERE / "catalog.json").read_text(encoding="utf-8"))
        for n, expected_count in ((1, 4), (2, 10), (3, 20), (4, 35)):
            expected = sorted((e for e in itertools.product(range(4), repeat=n) if sum(e) <= 3), key=lambda e: (sum(e), e))
            rows = catalog["by_n_inputs"][str(n)]
            self.assertEqual(len(rows), expected_count)
            self.assertEqual([row["exponents"] for row in rows], [list(e) for e in expected])
            self.assertEqual([row["feature_id"] for row in rows], ["m_" + "_".join(map(str, e)) for e in expected])
            self.assertEqual(api.make_spec(n, 1)["feature_ids"], [row["feature_id"] for row in rows])

    def test_spec_has_hash_bound_catalog_and_exact_term_budget(self):
        api = self.api()
        spec = api.make_spec(4, 16)
        self.assertEqual(spec["n_inputs"], 4)
        self.assertEqual(spec["k"], 16)
        self.assertEqual(spec["catalog_sha256"], hashlib.sha256((HERE / "catalog.json").read_bytes()).hexdigest())

    def test_spec_rejects_invalid_dimension_and_types(self):
        api = self.api()
        for n in (0, 5, True, False, 2.0, "2", None):
            with self.subTest(n=n), self.assertRaises(ValueError):
                api.make_spec(n, 1)

    def test_spec_rejects_invalid_k_and_types(self):
        api = self.api()
        for k in (0, -1, 17, True, False, 2.0, "2", None):
            with self.subTest(k=k), self.assertRaises(ValueError):
                api.make_spec(4, k)
        with self.assertRaises(ValueError):
            api.make_spec(1, 5)

    def test_validation_canonicalizes_without_mutating_submission(self):
        api = self.api()
        payload = self.payload()
        before = copy.deepcopy(payload)
        manifest = api.validate_submission(payload, api.make_spec(2, 3))
        self.assertEqual(manifest["feature_ids"], ["m_0_0", "m_0_1", "m_1_0"])
        self.assertEqual(payload, before)
        self.assertEqual(manifest["explanation"], payload["explanation"])

    def test_submission_requires_exact_two_fields(self):
        api = self.api()
        for field in ("source", "params", "n_params", "task_id", "k", "spec", "coefficients"):
            payload = self.payload()
            payload[field] = "untrusted"
            with self.subTest(field=field), self.assertRaises(ValueError):
                api.validate_submission(payload, api.make_spec(2, 3))
        for field in ("feature_ids", "explanation"):
            payload = self.payload()
            del payload[field]
            with self.assertRaises(ValueError):
                api.validate_submission(payload, api.make_spec(2, 3))

    def test_submission_rejects_non_dict_and_list_substitutes(self):
        api = self.api()
        for payload in (None, [], "{}", True):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                api.validate_submission(payload, api.make_spec(2, 3))
        for features in ((), "m_0_0", None, {}, True):
            with self.subTest(features=features), self.assertRaises(ValueError):
                api.validate_submission({"feature_ids": features, "explanation": "fixture"}, api.make_spec(2, 1))

    def test_requires_exact_k(self):
        api = self.api()
        for features in ([], ["m_0_0"], ["m_0_0", "m_0_1", "m_1_0", "m_1_1"]):
            with self.subTest(features=features), self.assertRaises(ValueError):
                api.validate_submission({"feature_ids": features, "explanation": "fixture"}, api.make_spec(2, 3))

    def test_requires_constant(self):
        api = self.api()
        with self.assertRaises(ValueError):
            api.validate_submission(self.payload(["m_1_0", "m_0_1"]), api.make_spec(2, 2))

    def test_rejects_duplicates_unknowns_and_feature_injection(self):
        api = self.api()
        for feature in ("m_0_0", "m_4_0", "m_-1_0", "m_1_0_0", "m_01_0", "x0", "m_1_0\nimport os", "__import__('os').system('echo injected')", True, 1, None, {}):
            with self.subTest(feature=feature), self.assertRaises(ValueError):
                api.validate_submission(self.payload(["m_0_0", feature]), api.make_spec(2, 2))

    def test_explanation_bounds_and_exact_type(self):
        api = self.api()
        for explanation in ("", " ", "\n\t", "a" * 2001, None, [], True, 3):
            with self.subTest(explanation=repr(explanation)[:40]), self.assertRaises(ValueError):
                api.validate_submission(self.payload(explanation=explanation), api.make_spec(2, 3))
        result = api.validate_submission(self.payload(explanation="a" * 2000), api.make_spec(2, 3))
        self.assertEqual(len(result["explanation"]), 2000)

    def test_rejects_forged_or_extended_trusted_spec(self):
        api = self.api()
        for field, value in (("catalog_sha256", "0" * 64), ("feature_ids", ["m_0_0"]), ("schema_version", "future"), ("arbitrary_code", "pass")):
            spec = api.make_spec(2, 3)
            spec[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                api.validate_submission(self.payload(), spec)

    def test_compilation_and_hashes_are_order_invariant(self):
        a = self.compile(["m_0_0", "m_1_0", "m_0_1"])
        b = self.compile(["m_1_0", "m_0_1", "m_0_0"])
        self.assertEqual(a, b)
        self.assertEqual(a["source_sha256"], hashlib.sha256(a["source"].encode("utf-8")).hexdigest())
        self.assertEqual(a["n_params"], 3)

    def test_explanation_never_becomes_executable_source_or_structure(self):
        a = self.compile(explanation="normal")
        b = self.compile(explanation="\nimport os\nos.remove('x')\n# narrative only")
        self.assertEqual(a["source"], b["source"])
        self.assertEqual(a["structural_sha256"], b["structural_sha256"])
        self.assertNotIn("import os", b["source"])

    def test_structure_and_source_change_with_features(self):
        a = self.compile(["m_0_0", "m_0_1"])
        b = self.compile(["m_0_0", "m_1_0"])
        self.assertNotEqual(a["source_sha256"], b["source_sha256"])
        self.assertNotEqual(a["structural_sha256"], b["structural_sha256"])

    def test_generated_ast_has_no_arbitrary_imports_or_divisions(self):
        compiled = self.compile(["m_0_0", "m_1_2", "m_3_0"])
        tree = ast.parse(compiled["source"])
        self.assertFalse(any(isinstance(node, (ast.Import, ast.ImportFrom, ast.Div, ast.FloorDiv)) for node in ast.walk(tree)))
        self.assertEqual([node.name for node in tree.body if isinstance(node, ast.FunctionDef)], ["equation"])

    def test_generated_equation_matches_hand_computed_direct_coefficients(self):
        compiled = self.compile(["m_0_0", "m_1_0", "m_0_1", "m_1_1", "m_2_0"])
        # Canonical basis: 1, x1, x0, x0*x1, x0**2.
        got = self.evaluate(compiled, [-2, 0, 3], [1, 2, -1], [2, 7, -3, 4, -5])
        np.testing.assert_array_equal(got, [-13, 16, -71])

    def test_constant_only_uses_each_row_and_does_not_mutate_inputs(self):
        compiled = self.compile(["m_0"], n_inputs=1)
        inputs = np.array([[1, 2], [3, 4]], dtype=np.int64)
        original = inputs.copy()
        got = self.evaluate(compiled, inputs, [3.5])
        np.testing.assert_array_equal(got, [3.5, 3.5, 3.5, 3.5])
        np.testing.assert_array_equal(inputs, original)
        self.assertEqual(got.dtype, np.dtype("float64"))

    def test_every_catalog_monomial_has_correct_synthetic_value(self):
        api = self.api()
        for n in range(1, 5):
            spec = api.make_spec(n, 1)
            constant = "m_" + "_".join(["0"] * n)
            values = [2, 3, 5, 7][:n]
            for feature in spec["feature_ids"]:
                selected = [constant] if feature == constant else [constant, feature]
                compiled = self.compile(selected, n_inputs=n)
                params = [1] if feature == constant else [0, 1]
                expected = 1
                for value, exponent in zip(values, map(int, feature[2:].split("_"))):
                    expected *= value ** exponent
                with self.subTest(n=n, feature=feature):
                    got = self.evaluate(compiled, *([[v]] for v in values), params)
                    np.testing.assert_array_equal(got, [expected])

    def test_generated_equation_rejects_wrong_parameter_shape_and_nonfinite(self):
        compiled = self.compile()
        for params in (1, [1, 2], [1, 2, 3, 4], [[1, 2, 3]], [1, np.nan, 3], [1, np.inf, 3]):
            with self.subTest(params=params), self.assertRaises(ValueError):
                self.evaluate(compiled, [1], [2], params)

    def test_generated_equation_rejects_mismatched_or_nonfinite_inputs(self):
        compiled = self.compile()
        for left, right in (([1, 2], [3]), ([1, np.nan], [2, 3]), ([np.inf], [1]), ([], [])):
            with self.subTest(left=left, right=right), self.assertRaises(ValueError):
                self.evaluate(compiled, left, right, [1, 1, 1])

    def test_final_guard_handles_overflow_consistently(self):
        compiled = self.compile(["m_0", "m_3"], n_inputs=1)
        got = self.evaluate(compiled, [1e200, -1e200, 1], [0, 1])
        np.testing.assert_array_equal(got, [1e6, -1e6, 1])

    def test_comparison_unchanged_ignores_narrative_and_input_order(self):
        api = self.api()
        result = api.compare_structure(self.compile(), self.compile(["m_1_0", "m_0_0", "m_0_1"], explanation="changed words"))
        self.assertEqual(result["classification"], "unchanged")
        self.assertTrue(result["same_k"])
        self.assertEqual(result["added"], [])
        self.assertEqual(result["removed"], [])

    def test_comparison_fixed_k_exchange(self):
        api = self.api()
        result = api.compare_structure(self.compile(["m_0_0", "m_1_0"]), self.compile(["m_0_0", "m_1_1"]))
        self.assertEqual(result["classification"], "same_k_exchange")
        self.assertEqual(result["kept"], ["m_0_0"])
        self.assertEqual(result["removed"], ["m_1_0"])
        self.assertEqual(result["added"], ["m_1_1"])
        self.assertEqual(result["claim_scope"], "feature_identity_only_no_performance_or_capacity_claim")

    def test_comparison_add_remove_and_mixed_cases_are_separate(self):
        api = self.api()
        a = self.compile(["m_0_0", "m_1_0"])
        b = self.compile(["m_0_0", "m_1_0", "m_0_1"])
        c = self.compile(["m_0_0", "m_1_1", "m_0_2"])
        self.assertEqual(api.compare_structure(a, b)["classification"], "term_addition")
        self.assertEqual(api.compare_structure(b, a)["classification"], "term_removal")
        self.assertEqual(api.compare_structure(a, c)["classification"], "mixed_add_remove_different_k")

    def test_comparison_revalidates_and_rejects_different_input_spaces(self):
        api = self.api()
        bad = self.compile()
        bad["feature_ids"] = ["m_0_0", "bad", "m_1_0"]
        with self.assertRaises(ValueError):
            api.compare_structure(self.compile(), bad)
        with self.assertRaises(ValueError):
            api.compare_structure(self.compile(), self.compile(["m_0"], n_inputs=1))


if __name__ == "__main__":
    result = unittest.main(exit=False)
    print(json.dumps({"synthetic_equation_calls": SYNTHETIC_EQUATION_CALLS, "fits": 0, "dataset_reads": 0}))
    raise SystemExit(0 if result.result.wasSuccessful() else 1)
