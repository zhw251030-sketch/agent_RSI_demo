"""Diagnostic feedback through the real SDK, with no API or task execution.

Only the provider transport, evaluator, and public planning TaskViews are faked.
The controller, tool serialization, conversation loop, and request ledger are real.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    SDK_PRESENT = importlib.util.find_spec("openhands.sdk") is not None
except ModuleNotFoundError:
    SDK_PRESENT = False

if SDK_PRESENT:
    from litellm.types.utils import ModelResponse
    from rsi_eval.diagnostic_controller import DiagnosticController
    from rsi_eval.pilot_agent import BoundedPilotLLM, run_session
    from rsi_eval.pilot_budget import BudgetLedger
    from rsi_eval.planning_trace import CandidateTrace
    from rsi_eval.symbolic_diagnostics import summarize_residuals


@unittest.skipUnless(SDK_PRESENT, "OpenHands SDK is not installed in this interpreter")
class DiagnosticSDKTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "fixtures").mkdir()
        (self.root / "prompts").mkdir()
        (self.root / "fixtures/initial.py").write_bytes(b"# fixed baseline\n")
        (self.root / "prompts/task.md").write_text(
            "Use the supplied public task interface.\n"
            "## Fixed revision procedure\nOriginal revision policy.", encoding="utf-8")

    def controller(self, family, arm, suffix=""):
        task_ids = ([f"spannerlearning/seed0/problem{i}" for i in range(10)]
                    if family == "planning" else ["oscillator1"])
        config = {
            "session_id": family, "family": family,
            "prompt_file": "prompts/task.md", "initial_candidate": "fixtures/initial.py",
            "initial_candidate_sha256": hashlib.sha256(b"# fixed baseline\n").hexdigest(),
            "initial_n_params": 0 if family == "planning" else 1,
            "task_ids": task_ids, "prompt_task_ids": task_ids[:2] if family == "planning" else [],
            "strategy_version": "fixed-revision-v0.1", "max_generated_candidates": 3,
        }
        policy = ("State a falsifiable prediction and cite diagnostic evidence."
                  if arm == "C" else "Revise from observed feedback.")
        return DiagnosticController(self.root, config, self.root / (family + arm + suffix),
                                    arm=arm, policy_text=policy)

    @staticmethod
    def evaluate(family, task_id, source, **kwargs):
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        result = {"status": "task_failure" if family == "planning" else "success",
                  "candidate_hash": digest, "run_id": "a" * 32}
        diagnostic = {"version": "diagnostics-v0.1", "task_id": task_id,
                      "candidate_sha256": digest,
                      "scope": "public_prompt" if family == "planning" else "train"}
        if family == "planning":
            # Development tasks retain ordinary scores, never private state traces.
            if task_id not in [f"spannerlearning/seed0/problem{i}" for i in range(2)]:
                return result
            diagnostic.update(trace=CandidateTrace().snapshot(), plan_replay={
                "status": "goal_not_reached", "executed_actions": 0, "plan_length": 0,
                "unsatisfied_goals": [["tightened", "nut0"]],
                "unsatisfied_goals_truncated": False,
            })
        else:
            result["metrics"] = {"mse": 1.0, "nmse": 1.0}
            diagnostic["residuals"] = summarize_residuals(
                [[0.0], [1.0]], [0.0, 1.0], [1.0, 2.0], ["x"])
        result["diagnostics"] = diagnostic
        return result

    @staticmethod
    def response(index, tool_name=None, source=None):
        message = {"role": "assistant", "content": "Observed the development feedback."}
        if tool_name:
            arguments = ({"source": source, "n_params": 1, "rationale": "Check this revision."}
                         if tool_name == "submit_candidate" else {"command": "must-not-run"})
            message["tool_calls"] = [{"id": f"call-{index}", "type": "function",
                                      "function": {"name": tool_name,
                                                   "arguments": json.dumps(arguments)}}]
        return ModelResponse(id=f"response-{index}", model="minimax-m3", choices=[{
            "message": message, "finish_reason": "tool_calls" if tool_name else "stop"}],
            usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120})

    def run_fake_session(self, controller, responses):
        session_id = controller.output_dir.name
        output = controller.output_dir / "sdk"
        ledger = BudgetLedger(output / "budget-ledger.json", max_requests=4,
                              session_ids=[session_id])
        llm = BoundedPilotLLM(
            model="anthropic/minimax-m3", api_key="fake-diagnostic-sdk-key",
            base_url="https://example.invalid", max_output_tokens=4096, num_retries=0,
            caching_prompt=False, api_mode="chat", stream=False,
            reasoning_effort="none").bind_pilot(ledger, session_id, output / "requests")
        with patch("rsi_eval.diagnostic_controller.evaluate_candidate", side_effect=self.evaluate) as evaluator, \
                patch("rsi_eval.pilot_controller.planning.prepare_task",
                      side_effect=lambda task_id, root: {"task_id": task_id, "objects": []}) as prepare, \
                patch("openhands.sdk.llm.llm.litellm_completion", side_effect=responses) as transport, \
                patch("openhands.sdk.conversation.impl.local_conversation.load_available_plugins",
                      side_effect=AssertionError("ambient plugin discovery")), \
                patch("openhands.sdk.conversation.impl.local_conversation.register_file_agents",
                      side_effect=AssertionError("ambient agent discovery")):
            controller.baseline()
            report = run_session(controller, llm, session_id, output)
        requests = [json.loads(path.read_text(encoding="utf-8"))
                    for path in sorted((output / "requests").glob("*.request.json"))]
        self.assertEqual(report["tools"], ["finish", "submit_candidate"])
        self.assertEqual(transport.call_count, len(responses), report)
        self.assertEqual(ledger.summary()["request_count"], len(responses))
        self.assertEqual(ledger.summary()["known_total_tokens"], 120 * len(responses))
        self.assertEqual(ledger.summary()["usage_unknown_count"], 0)
        self.assertEqual([call.args[0] for call in prepare.call_args_list], controller.prompt_ids)
        self.assertTrue(all(call.kwargs["diagnostics"] is True for call in evaluator.call_args_list))
        self.assertEqual({call.args[1] for call in evaluator.call_args_list}, set(controller.task_ids))
        for request, call in zip(requests, transport.call_args_list):
            self.assertEqual({tool["function"]["name"] for tool in request["tools"]},
                             {"finish", "submit_candidate"})
            self.assertEqual(call.kwargs["max_retries"], 0)
        for path in output.rglob("*.json"):
            self.assertNotIn("fake-diagnostic-sdk-key", path.read_text(encoding="utf-8"))
        return report, requests, evaluator

    @staticmethod
    def message_text(message):
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        return "\n".join(part.get("text", "") for part in content if isinstance(part, dict))

    def test_diagnostics_survive_actual_tool_round_trip_only_in_b_and_c(self):
        for family in ("planning", "symbolic"):
            digests = []
            visible = []
            for arm in "ABC":
                with self.subTest(family=family, arm=arm):
                    controller = self.controller(family, arm)
                    source = "def candidate(*args):\n    return []\n"
                    report, requests, evaluator = self.run_fake_session(controller, [
                        self.response(1, "submit_candidate", source), self.response(2)])
                    self.assertEqual(report["status"], "completed", report)
                    self.assertEqual(report["controller"]["generated_candidates"], 1)
                    self.assertEqual(evaluator.call_count, 2 * len(controller.task_ids))
                    digests.append(controller.initial_observation_digest())
                    tool_messages = [message for message in requests[1]["messages"]
                                     if message["role"] == "tool"]
                    self.assertEqual(len(tool_messages), 1)
                    feedback_text = self.message_text(tool_messages[0])
                    self.assertEqual(tool_messages[0]["tool_call_id"], "call-1")
                    self.assertIn(json.dumps(controller.records[1], ensure_ascii=False,
                                             allow_nan=False, sort_keys=True), feedback_text)
                    diagnostics = controller.hidden_observations[family + "-001"]
                    self.assertEqual(len(diagnostics), 2 if family == "planning" else 1)
                    for packet in diagnostics:
                        self.assertEqual(packet["candidate_sha256"], hashlib.sha256(source.encode()).hexdigest())
                        for evidence_id in packet["evidence_ids"]:
                            if arm == "A":
                                self.assertNotIn(evidence_id, json.dumps(requests))
                            else:
                                self.assertIn(evidence_id, feedback_text)
                    if arm == "A":
                        for request in requests:
                            for message in request["messages"]:
                                self.assertNotIn('"diagnostics":', self.message_text(message))
                    else:
                        self.assertIn('"diagnostics":', feedback_text)
                        self.assertIn('"diagnostics":', self.message_text(next(
                            message for message in requests[0]["messages"] if message["role"] == "user")))
                        visible.append(diagnostics)
                    self.assertFalse(report["controller"]["strategy_updated"])
                    self.assertEqual(report["controller"]["sealed_tasks_executed"], 0)
            self.assertEqual(len(set(digests)), 1)
            self.assertEqual(visible[0], visible[1])

    def test_fourth_submission_is_rejected_by_real_controller_in_every_arm(self):
        for arm in "ABC":
            with self.subTest(arm=arm):
                controller = self.controller("symbolic", arm, "cap")
                responses = [self.response(index, "submit_candidate", f"# candidate {index}\n")
                             for index in range(1, 5)]
                report, requests, evaluator = self.run_fake_session(controller, responses)
                self.assertEqual(report["status"], "stopped", report)
                self.assertIsNone(report["model_error_type"])
                self.assertEqual(report["controller"]["generated_candidates"], 3)
                self.assertEqual(report["controller"]["tool_rejections"], 1)
                self.assertEqual(evaluator.call_count, 4)  # Baseline plus three accepted candidates.
                self.assertEqual(controller.rejections, [{"status": "budget_exhausted",
                                                          "error_kind": "candidate_budget_exhausted"}])
                self.assertEqual(len(controller.records), 4)
                self.assertFalse((controller.output_dir / "candidates/symbolic-004.py").exists())
                # Request four has already received the third candidate's zero remaining budget.
                last_feedback = self.message_text([message for message in requests[3]["messages"]
                                                   if message["role"] == "tool"][-1])
                self.assertIn('"generated_candidates_remaining": 0', last_feedback)

    def test_unadvertised_tool_is_rejected_before_controller_dispatch(self):
        for tool_name in ("terminal", "read_file", "delegate"):
            with self.subTest(tool_name=tool_name):
                controller = self.controller("symbolic", "C", tool_name)
                report, _, evaluator = self.run_fake_session(
                    controller, [self.response(1, tool_name)])
                self.assertEqual(report["status"], "error", report)
                self.assertEqual(report["controller"]["generated_candidates"], 0)
                self.assertEqual(evaluator.call_count, 1)
                response_path = controller.output_dir / "sdk/requests/request-0001.response.json"
                saved = json.loads(response_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["error_type"], "PilotResponseContractError")
                self.assertEqual(saved["usage"]["total_tokens"], 120)


if __name__ == "__main__":
    unittest.main()
