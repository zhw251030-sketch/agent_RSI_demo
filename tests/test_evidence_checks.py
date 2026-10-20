"""Behavioral contracts for task-independent, bound evidence checks."""

import copy
import importlib
import importlib.util
import json
import math
import unittest


class EvidenceCheckTests(unittest.TestCase):
    def setUp(self):
        if importlib.util.find_spec("rsi_eval.evidence_checks") is None:
            self.fail("The structured evidence checker has not been implemented")
        self.checker = importlib.import_module("rsi_eval.evidence_checks")
        self.binding = {
            "session_id": "session-1", "candidate_id": "parent",
            "candidate_sha256": "a" * 64, "task_id": "task-1",
            "version": "evidence-v0.1", "scope": "development",
        }
        self.snapshot = {"binding": copy.deepcopy(self.binding),
                         "scalars": {"loss": 0.5, "absolute_bias": 0.02},
                         "facts": {"edges": [["from", "a", "b"]], "empty": []}}

    def reference(self, key="loss", **changes):
        return dict(self.binding, key=key, **changes)

    def scalar(self, value=0.5, op="eq", reference=None):
        return {"kind": "scalar", "reference": reference or self.reference(),
                "op": op, "value": value}

    def fact(self, value=None, op="contains", key="edges"):
        return {"kind": "fact", "reference": self.reference(key), "op": op,
                "value": ["from", "a", "b"] if value is None else value}

    def check(self, claim, snapshots=None):
        return self.checker.check_claim(claim, [self.snapshot] if snapshots is None else snapshots)

    def child(self, value, candidate_id="child", digest="b" * 64):
        result = copy.deepcopy(self.snapshot)
        result["binding"].update(candidate_id=candidate_id, candidate_sha256=digest)
        result["scalars"]["loss"] = value
        return result

    def registered(self, direction="decrease", min_delta=0.1):
        return self.checker.register_prediction(
            {"reference": self.reference(), "direction": direction,
             "min_delta": min_delta}, [self.snapshot])

    def test_scalar_comparisons_have_the_correct_direction(self):
        for op, value, expected in [("eq", 0.5, "supported"), ("lt", 0.6, "supported"),
                                    ("le", 0.4, "contradicted"), ("gt", 0.4, "supported"),
                                    ("ge", 0.6, "contradicted")]:
            with self.subTest(op=op):
                report = self.check(self.scalar(value, op))
                self.assertEqual(report["status"], expected)
                self.assertEqual(report["actual"], 0.5)
                self.assertEqual(report["expected"], value)

    def test_false_fact_is_contradicted_without_reversing_a_directed_edge(self):
        report = self.check(self.fact(["from", "b", "a"]))
        self.assertEqual(report["status"], "contradicted")
        self.assertEqual(report["actual"], False)
        self.assertEqual(self.check(self.fact())["status"], "supported")

    def test_empty_facts_are_known_empty_and_missing_facts_are_unavailable(self):
        self.assertEqual(self.check(self.fact(key="empty"))["status"], "contradicted")
        self.assertEqual(self.check(self.fact(op="not_contains", key="empty"))["status"], "supported")
        self.assertEqual(self.check(self.fact(key="missing"))["status"], "unavailable")

    def test_every_reference_binding_field_is_required_for_lookup(self):
        for field, value in [("session_id", "other-session"), ("candidate_id", "stale"),
                             ("candidate_sha256", "b" * 64), ("task_id", "other-task"),
                             ("version", "evidence-v0.2"), ("scope", "sealed")]:
            with self.subTest(field=field):
                reference = self.reference()
                reference[field] = value
                self.assertEqual(self.check(self.scalar(reference=reference))["status"], "unavailable")

    def test_distinct_candidates_with_same_metric_are_not_conflated(self):
        other = self.child(0.25)
        report = self.check(self.scalar(), [other, self.snapshot])
        self.assertEqual(report["actual"], 0.5)
        reference = dict(other["binding"], key="loss")
        self.assertEqual(self.check(self.scalar(0.25, reference=reference),
                                    [self.snapshot, other])["status"], "supported")

    def test_duplicate_exact_bindings_are_ambiguous_even_if_values_agree(self):
        self.assertEqual(self.check(self.scalar(), [self.snapshot, copy.deepcopy(self.snapshot)])["status"],
                         "unavailable")

    def test_missing_none_and_undefined_denominator_metrics_are_unavailable(self):
        self.snapshot["scalars"].update(loss=None, ratio_with_zero_denominator=None)
        for key in ["loss", "missing", "ratio_with_zero_denominator"]:
            with self.subTest(key=key):
                self.assertEqual(self.check(self.scalar(reference=self.reference(key)))["status"],
                                 "unavailable")

    def test_boolean_nonfinite_and_overflowing_integers_are_invalid_numbers(self):
        for value in [True, False, math.nan, math.inf, -math.inf, 10 ** 400]:
            with self.subTest(value_type=type(value).__name__):
                self.assertEqual(self.check(self.scalar(value))["status"], "schema_invalid")
                self.snapshot["scalars"]["loss"] = value
                self.assertEqual(self.check(self.scalar())["status"], "schema_invalid")

    def test_frozen_tolerance_applies_to_strict_and_nonstrict_operators(self):
        self.snapshot["scalars"]["loss"] = 1.0
        for op, value, expected in [("eq", 1.0 + 5e-9, "supported"),
                                    ("eq", 1.0 + 2e-8, "contradicted"),
                                    ("lt", 1.0 + 5e-9, "contradicted"),
                                    ("lt", 1.0 + 2e-8, "supported"),
                                    ("gt", 1.0 - 5e-9, "contradicted"),
                                    ("gt", 1.0 - 2e-8, "supported"),
                                    ("le", 1.0 - 5e-9, "supported"),
                                    ("ge", 1.0 + 5e-9, "supported")]:
            with self.subTest(op=op, value=value):
                self.assertEqual(self.check(self.scalar(value, op))["status"], expected)

    def test_absolute_tolerance_operates_near_zero(self):
        self.snapshot["scalars"]["loss"] = 0.0
        self.assertEqual(self.check(self.scalar(5e-11))["status"], "supported")
        self.assertEqual(self.check(self.scalar(2e-10))["status"], "contradicted")

    def test_absolute_bias_is_just_a_scalar_without_causal_inference(self):
        report = self.check(self.scalar(0.5, "gt", self.reference("absolute_bias")))
        self.assertEqual(report["status"], "contradicted")
        self.assertEqual(report["actual"], 0.02)

    def test_closed_claim_reference_snapshot_and_fact_schema(self):
        bad_claims = [None, [], {**self.scalar(), "explanation": "private"},
                      {**self.scalar(), "kind": "causal"},
                      {**self.scalar(), "op": "approximately"},
                      {**self.fact(), "op": "eq"}, self.fact([]), self.fact([1]),
                      self.fact(["from", True]), {**self.scalar(), "value": "0.5"}]
        for claim in bad_claims:
            with self.subTest(claim=claim):
                self.assertEqual(self.check(claim)["status"], "schema_invalid")
        for reference in [{**self.reference(), "private": "secret"},
                          {k: v for k, v in self.reference().items() if k != "scope"},
                          {**self.reference(), "candidate_sha256": "not-a-hash"}]:
            self.assertEqual(self.check(self.scalar(reference=reference))["status"], "schema_invalid")
        for mutate in [lambda s: s.update(private="secret"),
                       lambda s: s["binding"].update(private="secret"),
                       lambda s: s["facts"].update(edges=[[True]]),
                       lambda s: s["facts"].update(edges=None)]:
            snapshot = copy.deepcopy(self.snapshot)
            mutate(snapshot)
            self.assertEqual(self.check(self.scalar(), [snapshot])["status"], "schema_invalid")

    def test_invalid_large_inputs_produce_small_reports_without_echoing_them(self):
        huge = "sensitive-" * 100000
        inputs = [{**self.scalar(), "private": huge},
                  {**self.scalar(), "reference": {**self.reference(), "scope": huge}},
                  self.fact([huge]), {**self.scalar(), "value": [huge] * 100}]
        for claim in inputs:
            report = self.check(claim)
            self.assertEqual(report["status"], "schema_invalid")
            self.assertLess(len(json.dumps(report)), 8192)
            self.assertNotIn("sensitive", json.dumps(report))

    def test_fact_reports_do_not_echo_entire_fact_inventory(self):
        self.snapshot["facts"]["edges"] = [["edge", str(i), str(i + 1)] for i in range(400)]
        report = self.check(self.fact(["edge", "100", "101"]))
        self.assertEqual(report["status"], "supported")
        self.assertLess(len(json.dumps(report)), 8192)
        self.assertNotIn("399", json.dumps(report))

    def test_registration_captures_before_without_mutating_inputs(self):
        original = copy.deepcopy(self.snapshot)
        report = self.registered()
        self.assertEqual(report["status"], "supported")
        self.assertEqual(report["reason"], "prediction_registered")
        self.assertEqual(report["before"], 0.5)
        self.snapshot["scalars"]["loss"] = 7.0
        self.assertEqual(report["before"], 0.5)
        self.assertEqual(report["reference"], dict(original["binding"], key="loss"))

    def test_prediction_minimum_delta_uses_absolute_units(self):
        self.assertEqual(self.checker.check_prediction(self.registered(min_delta=0.1),
                                                      [self.child(0.44)])["status"], "contradicted")
        report = self.checker.check_prediction(self.registered(min_delta=0.1), [self.child(0.39)])
        self.assertEqual(report["status"], "supported")
        self.assertAlmostEqual(report["actual"], 0.11)
        self.assertEqual(report["expected"], 0.1)

    def test_increase_prediction_and_delta_tolerance(self):
        report = self.checker.check_prediction(self.registered("increase", 0.1), [self.child(0.6)])
        self.assertEqual(report["status"], "supported")
        self.assertEqual(self.checker.check_prediction(self.registered("increase", 0.1),
                                                      [self.child(0.5)])["status"], "contradicted")
        self.assertEqual(self.checker.check_prediction(self.registered(min_delta=0.1),
                                                      [self.child(0.40000000005)])["status"], "supported")

    def test_rejected_or_unselected_child_is_still_checked(self):
        # Selection belongs to the caller: these supplied child snapshots are
        # evaluated even though the caller will retain the better parent.
        report = self.checker.check_prediction(self.registered(), [self.child(0.9)])
        self.assertEqual(report["status"], "contradicted")
        self.assertEqual(report["after"], 0.9)
        self.assertAlmostEqual(report["actual"], -0.4)

    def test_missing_child_and_missing_child_metric_are_unavailable(self):
        registered = self.registered()
        for children in [[], [self.child(None)], [{**self.child(0.2), "scalars": {}}]]:
            self.assertEqual(self.checker.check_prediction(registered, children)["status"], "unavailable")

    def test_child_cannot_reuse_parent_id_or_cross_session_task_scope_version(self):
        registered = self.registered()
        self.assertEqual(self.checker.check_prediction(registered, [self.snapshot])["status"], "unavailable")
        same_id_new_hash = self.child(0.1, candidate_id="parent")
        self.assertEqual(self.checker.check_prediction(registered, [same_id_new_hash])["status"], "unavailable")
        for field in ["session_id", "task_id", "scope", "version"]:
            child = self.child(0.1)
            child["binding"][field] = "other"
            self.assertEqual(self.checker.check_prediction(registered, [child])["status"], "unavailable")

    def test_a_new_child_may_legitimately_repeat_the_parent_source_hash(self):
        report = self.checker.check_prediction(self.registered(), [self.child(0.5, digest="a" * 64)])
        self.assertEqual(report["status"], "contradicted")

    def test_multiple_children_are_ambiguous_and_not_cherry_picked(self):
        registered = self.registered()
        candidates = [self.child(0.1), self.child(0.8, "other-child", "c" * 64)]
        self.assertEqual(self.checker.check_prediction(registered, candidates)["status"], "unavailable")
        self.assertEqual(self.checker.check_prediction(registered, list(reversed(candidates)))["status"],
                         "unavailable")

    def test_prediction_schema_rejects_signed_invalid_and_boolean_minimum_delta(self):
        for value in [-0.1, True, math.nan, math.inf, "0.1", 10 ** 400]:
            report = self.checker.register_prediction(
                {"reference": self.reference(), "direction": "decrease", "min_delta": value},
                [self.snapshot])
            self.assertEqual(report["status"], "schema_invalid")
        for prediction in [{"reference": self.reference(), "direction": "unchanged", "min_delta": 0},
                           {"reference": self.reference(), "direction": "decrease", "min_delta": 0,
                            "selected_only": True}]:
            self.assertEqual(self.checker.register_prediction(prediction, [self.snapshot])["status"],
                             "schema_invalid")

    def test_registration_missing_or_fact_only_reference_is_unavailable(self):
        for key in ["missing", "edges"]:
            report = self.checker.register_prediction(
                {"reference": self.reference(key), "direction": "decrease", "min_delta": 0},
                [self.snapshot])
            self.assertEqual(report["status"], "unavailable")

    def test_unregistered_or_malformed_prediction_cannot_be_checked(self):
        for registered in [{"reference": self.reference(), "direction": "decrease", "min_delta": 0.1},
                           {**self.registered(), "before": True},
                           {**self.registered(), "private": "secret"},
                           {**self.registered(), "status": "contradicted"}]:
            self.assertEqual(self.checker.check_prediction(registered, [self.child(0.1)])["status"],
                             "schema_invalid")

    def test_extreme_finite_scalar_comparisons_do_not_emit_nonfinite_json(self):
        self.snapshot["scalars"]["loss"] = 1e308
        report = self.check(self.scalar(-1e308, "gt"))
        self.assertEqual(report["status"], "supported")
        json.dumps(report, allow_nan=False)
        registered = self.registered("decrease", 1.0)
        report = self.checker.check_prediction(registered, [self.child(-1e308)])
        self.assertEqual(report["status"], "unavailable")
        json.dumps(report, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
