"""Host replay observations from hand-checkable, hash-verified STRIPS tasks."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from rsi_eval import planning, planning_diagnostics
from tests.test_planning import DOMAIN, PROBLEM, TASK_ID


class PlanningDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.diagnostics = planning_diagnostics
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.manifest_path = self.root / "configs/tasks/planning-spanner-v0.1.json"
        self.manifest_path.parent.mkdir(parents=True)
        data = self.root / "data/planning/spanner"
        (data / "spannerlearning/seed0").mkdir(parents=True)
        self.domain_path = data / "spannerlearning.pddl"
        self.problem_path = data / "spannerlearning/seed0/problem0.pddl"
        self.manifest = {
            "domain": {"upstream_path": planning.PDDL_PREFIX + "spannerlearning.pddl"},
            "tasks": [{"id": TASK_ID,
                       "upstream_path": planning.PDDL_PREFIX + TASK_ID + ".pddl",
                       "pilot_role": "prompt"}],
        }
        self.write_task(DOMAIN, PROBLEM)

    def save_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def write_task(self, domain, problem):
        self.domain_path.write_bytes(domain.encode())
        self.problem_path.write_bytes(problem.encode())
        self.manifest["domain"]["sha256"] = hashlib.sha256(domain.encode()).hexdigest()
        self.manifest["tasks"][0]["sha256"] = hashlib.sha256(problem.encode()).hexdigest()
        self.save_manifest()

    def diagnose(self, plan):
        return self.diagnostics.diagnose_plan(TASK_ID, plan, self.root)

    def test_public_check_only_reads_manifest(self):
        self.domain_path.unlink()
        self.problem_path.unlink()
        self.assertTrue(self.diagnostics.is_public_prompt(TASK_ID, self.root))
        self.assertFalse(self.diagnostics.is_public_prompt(TASK_ID + "/extra", self.root))

    def test_nonpublic_roles_are_denied_before_task_reads(self):
        self.domain_path.unlink()
        self.problem_path.unlink()
        for role in ("development_feedback", "sealed_evaluation", "inventory_not_selected", None):
            with self.subTest(role=role):
                self.manifest["tasks"][0]["pilot_role"] = role
                self.save_manifest()
                self.assertFalse(self.diagnostics.is_public_prompt(TASK_ID, self.root))
                with self.assertRaises(PermissionError):
                    self.diagnose([])

    def test_unknown_and_duplicate_task_ids_are_denied(self):
        with self.assertRaises(PermissionError):
            self.diagnostics.diagnose_plan("../unknown", [], self.root)
        self.manifest["tasks"].append(dict(self.manifest["tasks"][0]))
        self.save_manifest()
        self.domain_path.unlink()
        self.problem_path.unlink()
        self.assertFalse(self.diagnostics.is_public_prompt(TASK_ID, self.root))
        with self.assertRaises(PermissionError):
            self.diagnose([])

    def test_integrity_failure_is_not_reported_as_plan_failure(self):
        self.problem_path.write_bytes((PROBLEM + "\n; altered").encode())
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.diagnose([])

    def test_empty_plan_reports_initial_unsatisfied_goal(self):
        result = self.diagnose([])
        self.assertEqual(result["status"], "goal_unsatisfied")
        self.assertEqual(result["executed_actions"], 0)
        self.assertEqual(result["plan_length"], 0)
        self.assertIsNone(result["first_failed_action"])
        self.assertEqual(result["missing_preconditions"], [])
        self.assertEqual(result["unsatisfied_goals"], [["tightened", "nut1"]])
        self.assertFalse(result["unsatisfied_goals_truncated"])

    def test_empty_plan_can_satisfy_goal_without_validator(self):
        self.write_task(DOMAIN, PROBLEM.replace("(and (tightened nut1))", "(and (at bob shed))"))
        result = self.diagnose([])
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["unsatisfied_goals"], [])

    def test_positive_effect_satisfies_goal_with_typed_subclass_argument(self):
        self.write_task(DOMAIN, PROBLEM.replace("(and (tightened nut1))", "(and (at bob gate))"))
        result = self.diagnose(["  (WALK SHED GATE BOB)  "])
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["executed_actions"], 1)
        self.assertEqual(result["plan_length"], 1)
        self.assertEqual(result["unsatisfied_goals"], [])
        self.assertIsNone(result["error_kind"])

    def test_negative_effect_removes_previously_satisfied_goal(self):
        self.write_task(DOMAIN, PROBLEM.replace("(and (tightened nut1))", "(and (at bob shed))"))
        result = self.diagnose(["(walk shed gate bob)"])
        self.assertEqual(result["status"], "goal_unsatisfied")
        self.assertEqual(result["unsatisfied_goals"], [["at", "bob", "shed"]])

    def test_first_failed_action_stops_replay_without_applying_its_effects(self):
        self.write_task(DOMAIN, PROBLEM.replace("(and (tightened nut1))", "(and (at bob shed))"))
        result = self.diagnose(["(walk shed gate bob)", "(walk gate shed bob)", "(walk shed gate bob)"])
        self.assertEqual(result["status"], "precondition_failure")
        self.assertEqual(result["executed_actions"], 1)
        self.assertEqual(result["plan_length"], 3)
        self.assertEqual(result["first_failed_action"], {"index": 1, "action": "(walk gate shed bob)"})
        self.assertEqual(result["missing_preconditions"], [["link", "gate", "shed"]])
        self.assertEqual(result["unsatisfied_goals"], [["at", "bob", "shed"]])

    def test_deleted_fact_is_missing_for_later_action(self):
        result = self.diagnose(["(walk shed gate bob)", "(walk shed gate bob)"])
        self.assertEqual(result["status"], "precondition_failure")
        self.assertEqual(result["executed_actions"], 1)
        self.assertEqual(result["missing_preconditions"], [["at", "bob", "shed"]])

    def test_plan_format_and_argument_errors_are_rejected_before_replay(self):
        cases = [
            (None, "output_not_plan"),
            (["(walk shed gate)"], "operator_arity"),
            (["(walk bob gate bob)"], "object_type"),
            (["(walk shed nowhere bob)"], "unknown_object"),
            (["(teleport shed gate bob)"], "unknown_operator"),
            (["(walk shed gate bob); secret-content"], "operator_syntax"),
            ([3], "operator_syntax"),
        ]
        for plan, kind in cases:
            with self.subTest(kind=kind):
                result = self.diagnose(plan)
                self.assertEqual(result["status"], "invalid_output")
                self.assertEqual(result["error_kind"], kind)
                self.assertEqual(result["executed_actions"], 0)
                self.assertEqual(result["missing_preconditions"], [])
                self.assertEqual(result["unsatisfied_goals"], [])
                self.assertNotIn("secret-content", json.dumps(result))

    def test_invalid_later_action_prevents_partial_replay(self):
        result = self.diagnose(["(walk shed gate bob)", "(walk gate shed)"])
        self.assertEqual(result["status"], "invalid_output")
        self.assertEqual(result["executed_actions"], 0)
        self.assertEqual(result["first_failed_action"], {"index": 1, "action": None})

    def test_action_and_plan_limits_do_not_echo_oversized_input(self):
        for plan in (["(walk " + "a" * 4096 + ")"], ["(walk shed gate bob)"] * 1001):
            with self.subTest(length=len(plan)):
                result = self.diagnose(plan)
                self.assertEqual(result["status"], "invalid_output")
                self.assertEqual(result["executed_actions"], 0)
                self.assertLess(len(json.dumps(result)), 1000)

    def test_nonbuiltin_container_is_not_inspected(self):
        class UnsafeList(list):
            def __len__(self):
                raise AssertionError("Untrusted length was executed")

        result = self.diagnose(UnsafeList())
        self.assertEqual(result["status"], "invalid_output")
        self.assertIsNone(result["plan_length"])

    def test_thousand_action_boundary_is_accepted(self):
        problem = PROBLEM.replace("(link shed gate)", "(link shed gate) (link gate shed)")
        problem = problem.replace("(and (tightened nut1))", "(and (at bob shed))")
        self.write_task(DOMAIN, problem)
        result = self.diagnose(["(walk shed gate bob)", "(walk gate shed bob)"] * 500)
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["executed_actions"], 1000)

    def test_fact_observations_are_sorted_deterministic_and_capped(self):
        predicates = " ".join("(need%02d)" % i for i in reversed(range(25)))
        domain = """(define (domain spanner) (:requirements :typing :strips)
          (:types thing - object) (:predicates %s)
          (:action finish :parameters () :precondition (and %s) :effect (and)))""" % (predicates, predicates)
        problem = """(define (problem capped) (:domain spanner) (:objects)
          (:init) (:goal (and %s)))""" % predicates
        self.write_task(domain, problem)
        result = self.diagnose(["(finish)"])
        self.assertEqual(result, self.diagnose(["(finish)"]))
        expected = [["need%02d" % i] for i in range(20)]
        self.assertEqual(result["missing_preconditions"], expected)
        self.assertEqual(result["unsatisfied_goals"], expected)
        self.assertTrue(result["missing_preconditions_truncated"])
        self.assertTrue(result["unsatisfied_goals_truncated"])
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)
        self.assertNotIn(str(self.root), json.dumps(result))


if __name__ == "__main__":
    unittest.main()
