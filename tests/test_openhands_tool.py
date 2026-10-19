"""Real SDK schema/dispatch tests; no model calls or dataset access."""
import importlib.util
import json
import unittest
from unittest.mock import patch

try:
    SDK_PRESENT = importlib.util.find_spec("openhands.sdk") is not None
except ModuleNotFoundError:
    SDK_PRESENT = False

if SDK_PRESENT:
    from pydantic import ValidationError
    from rsi_eval.openhands_tool import EvaluateCandidateAction, EvaluateCandidateTool


@unittest.skipUnless(SDK_PRESENT, "OpenHands SDK is not installed in this interpreter")
class OpenHandsEvaluationToolTests(unittest.TestCase):
    def test_action_rejects_path_shell_root_and_unbounded_parameters(self):
        valid = {"family": "planning", "task_id": "spannerlearning/seed0/problem0", "source": "pass"}
        for extra in ({"root": "/tmp"}, {"path": "/tmp/candidate.py"}, {"command": "echo hi"},
                      {"family": "shell"}, {"n_params": 17}, {"n_params": True},
                      {"source": "x" * 65537}):
            with self.subTest(extra=list(extra)), self.assertRaises(ValidationError):
                EvaluateCandidateAction.model_validate({**valid, **extra})

    def test_actual_sdk_dispatch_filters_private_fields_and_candidate_diagnostics(self):
        tool, = EvaluateCandidateTool.create()
        action = tool.action_from_arguments({"family": "planning", "task_id": "spannerlearning/seed0/problem0",
                                             "source": "def get_plan(*args): return []"})
        raw = {"status": "task_failure", "error_kind": "plan_semantics", "plan_length": 0,
               "public_diagnostic": "private /host/path must not be echoed", "raw_stdout": "SECRET",
               "validator": {"stdout": "SECRET"}, "y": [99], "candidate_hash": "a" * 64,
               "task_id": action.task_id, "family": "planning", "elapsed_seconds": 0.1}
        with patch("rsi_eval.openhands_tool.evaluate_candidate", return_value=raw):
            observation = tool(action)
        self.assertEqual(observation.feedback["status"], "task_failure")
        self.assertEqual(observation.feedback["plan_length"], 0)
        self.assertNotIn("SECRET", observation.text)
        self.assertNotIn("/host/path", observation.text)
        self.assertNotIn("validator", observation.feedback)
        self.assertNotIn("y", observation.feedback)
        self.assertEqual(json.loads(observation.text), observation.feedback)

    def test_success_keeps_finite_metrics_and_explicit_training_scope(self):
        tool, = EvaluateCandidateTool.create()
        action = EvaluateCandidateAction(family="symbolic", task_id="oscillator1", source="pass", n_params=1)
        raw = {"status": "success", "family": "symbolic", "task_id": "oscillator1",
               "metrics": {"mse": 2.0, "nmse": 0.25, "fake_test_score": 1.0},
               "metric_split": "train", "metric_scope": "arbitrary text"}
        with patch("rsi_eval.openhands_tool.evaluate_candidate", return_value=raw):
            observation = tool(action)
        self.assertFalse(observation.is_error)
        self.assertEqual(observation.feedback["metrics"], {"mse": 2.0, "nmse": 0.25})
        self.assertEqual(observation.feedback["metric_split"], "train")
        self.assertIn("not a held-out", observation.feedback["metric_scope"])

    def test_tool_schema_exposes_only_candidate_evaluation(self):
        tool, = EvaluateCandidateTool.create()
        schema = tool.to_mcp_tool()
        self.assertEqual(schema["name"], "evaluate_candidate")
        self.assertNotIn("root", schema["inputSchema"]["properties"])
        self.assertNotIn("path", schema["inputSchema"]["properties"])
        with self.assertRaises(ValueError):
            EvaluateCandidateTool.create(root="/tmp")


if __name__ == "__main__":
    unittest.main()
