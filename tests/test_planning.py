"""Planning adapter boundary tests, using small hand-authored PDDL fixtures."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from rsi_eval import planning, planning_worker


DOMAIN = """(define (domain spanner)
 (:requirements :typing :strips)
 (:types location locatable - object man nut spanner - locatable)
 (:predicates (at ?m - locatable ?l - location)
  (link ?a - location ?b - location) (tightened ?n - nut))
 (:action walk :parameters (?start - location ?end - location ?m - man)
  :precondition (and (at ?m ?start) (link ?start ?end))
  :effect (and (not (at ?m ?start)) (at ?m ?end))))"""
PROBLEM = """(define (problem small) (:domain spanner)
 (:objects bob - man nut1 - nut shed gate - location)
 (:init (at bob shed) (at nut1 gate) (link shed gate))
 (:goal (and (tightened nut1))))"""
TASK_ID = "spannerlearning/seed0/problem0"


class PlanningAdapterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.manifest_path = self.root / "configs/tasks/planning-spanner-v0.1.json"
        self.manifest_path.parent.mkdir(parents=True)
        data = self.root / "data/planning/spanner"
        (data / "spannerlearning/seed0").mkdir(parents=True)
        (data / "spannerlearning.pddl").write_bytes(DOMAIN.encode())
        self.problem_path = data / "spannerlearning/seed0/problem0.pddl"
        self.problem_path.write_bytes(PROBLEM.encode())
        self.manifest = {
            "domain": {"upstream_path": planning.PDDL_PREFIX + "spannerlearning.pddl",
                       "sha256": hashlib.sha256(DOMAIN.encode()).hexdigest()},
            "tasks": [{"id": TASK_ID,
                       "upstream_path": planning.PDDL_PREFIX + TASK_ID + ".pddl",
                       "sha256": hashlib.sha256(PROBLEM.encode()).hexdigest(),
                       "pilot_role": "prompt"}],
        }
        self.save_manifest()

    def save_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def test_typed_input_is_normalized_without_host_paths(self):
        request = planning.prepare_task(TASK_ID, self.root)
        self.assertEqual(set(request), {"family", "task_id", "objects", "init", "goal"})
        self.assertEqual(request["family"], "planning")
        self.assertIn(["bob", "man"], request["objects"])
        self.assertIn(["at", "bob", "shed"], request["init"])
        self.assertEqual(request["goal"], [["tightened", "nut1"]])

    def test_sealed_and_inventory_are_rejected_before_reading_files(self):
        self.problem_path.unlink()
        for role in ("sealed_evaluation", "inventory_not_selected"):
            with self.subTest(role=role):
                self.manifest["tasks"][0]["pilot_role"] = role
                self.save_manifest()
                with self.assertRaises(PermissionError):
                    planning.prepare_task(TASK_ID, self.root)

    def test_changed_problem_is_not_silently_loaded(self):
        self.problem_path.write_bytes((PROBLEM + "\n; changed").encode())
        with self.assertRaisesRegex(ValueError, "integrity"):
            planning.prepare_task(TASK_ID, self.root)

    def test_rejects_unsupported_goal_and_domain_forms(self):
        domain = planning.parse_domain(DOMAIN)
        for goal in ("(or (tightened nut1) (tightened nut1))", "(not (tightened nut1))",
                     "(forall (?n - nut) (tightened ?n))"):
            with self.subTest(goal=goal), self.assertRaises(ValueError):
                planning.parse_problem(PROBLEM.replace("(and (tightened nut1))", goal), domain)
        with self.assertRaises(ValueError):
            planning.parse_domain(DOMAIN.replace(":typing :strips", ":typing :strips :adl"))
        with self.assertRaises(ValueError):
            planning.parse_domain(DOMAIN.replace("(at ?m ?end))))", "(when (at ?m ?start) (at ?m ?end)))))"))

    def test_ground_facts_enforce_object_type(self):
        with self.assertRaises(ValueError):
            planning.parse_problem(PROBLEM.replace("(at bob shed)", "(at shed bob)"), planning.parse_domain(DOMAIN))

    def test_action_errors_never_reach_missing_validator(self):
        cases = [
            ("not-a-list", "output_not_plan"),
            (["(teleport shed gate bob)"], "unknown_operator"),
            (["(walk shed gate)"], "operator_arity"),
            (["(walk shed nowhere bob)"], "unknown_object"),
            (["(walk bob gate bob)"], "object_type"),
            (["(walk shed gate bob) ; extra"], "operator_syntax"),
            (["(walk shed gate bob)"] * 1001, "plan_too_long"),
        ]
        for candidate, error in cases:
            with self.subTest(error=error):
                result = planning.validate_plan(TASK_ID, candidate, self.root)
                self.assertEqual(result["status"], "invalid_output")
                self.assertEqual(result["error_kind"], error)

    def test_missing_validator_is_infrastructure_not_task_failure(self):
        result = planning.validate_plan(TASK_ID, [], self.root)
        self.assertEqual(result["status"], "infrastructure_error")
        self.assertEqual(result["error_kind"], "validator_integrity")

    def test_worker_memory_error_reaches_resource_limit_handler(self):
        request = planning.prepare_task(TASK_ID, self.root)
        with self.assertRaises(MemoryError):
            planning_worker.run("raise MemoryError()", request)

    def test_worker_exception_diagnostic_only_identifies_candidate_line(self):
        request = planning.prepare_task(TASK_ID, self.root)
        source = "def get_plan(objects, init, goal):\n    raise ValueError('private-message')\n"
        result = planning_worker.run(source, request)
        self.assertEqual(result["status"], "candidate_error")
        self.assertEqual(result["exception_type"], "ValueError")
        self.assertEqual(result["candidate_line"], 2)
        self.assertNotIn("private-message", json.dumps(result))
        self.assertNotIn(str(self.root), json.dumps(result))


if __name__ == "__main__":
    unittest.main()
