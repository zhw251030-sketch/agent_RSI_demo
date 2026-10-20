"""Actual OpenHands integration with a fake transport; no credentials or API calls."""
import importlib.util
import hashlib
import json
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch, Mock

try:
    SDK_PRESENT = importlib.util.find_spec("openhands.sdk") is not None
except ModuleNotFoundError:
    SDK_PRESENT = False

if SDK_PRESENT:
    from litellm.types.utils import ModelResponse
    from pydantic import ValidationError
    from rsi_eval.pilot_agent import BoundedPilotLLM, SubmitCandidateAction, create_conversation, run_session


class FakeController:
    def __init__(self):
        self.calls = []

    def task_prompt(self):
        return "Submit a candidate defining get_plan(objects, init, goal), then finish."

    def submit(self, source, n_params=3, rationale=""):
        self.calls.append((source, n_params, rationale))
        return {"status": "success", "development_success_count": 10}

    def summary(self):
        return {"candidate_count": len(self.calls)}


class FakeLedger:
    def __init__(self, limit=8):
        self.requests = []
        self.settlements = []
        self.limit = limit

    def reserve(self, session_id, request_payload, output_tokens):
        if len(self.requests) >= self.limit:
            raise RuntimeError("budget denied")
        self.requests.append((session_id, request_payload, output_tokens))
        return str(len(self.requests))

    def settle(self, request_id, usage, error_type=None):
        self.settlements.append((request_id, usage, error_type))


@unittest.skipUnless(SDK_PRESENT, "OpenHands SDK is not installed in this interpreter")
class PilotAgentTests(unittest.TestCase):
    def llm(self, ledger, path):
        return BoundedPilotLLM(model="anthropic/minimax-m3", api_key="fake-test-key",
                               base_url="https://example.invalid", max_output_tokens=4096,
                               num_retries=0, caching_prompt=False, api_mode="chat",
                               stream=False, reasoning_effort="none").bind_pilot(ledger, "test", path)

    def test_schema_rejects_task_path_command_and_boolean_parameter_count(self):
        for fields in ({"task_id": "secret"}, {"root": "/"}, {"command": "cat"}, {"n_params": True}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                SubmitCandidateAction(source="pass", **fields)

    def test_runner_rejects_budget_expansion_and_wrong_sessions(self):
        from scripts.run_agent_pilot import validate_config
        config = {"sessions": [{"session_id": name, "family": name, "max_generated_candidates": 3}
                               for name in ("planning", "symbolic")],
                  "budgets": {"max_requests": 8, "max_requests_per_session": 4,
                              "max_output_tokens": 4096, "max_input_bytes": 98304,
                              "max_reserved_tokens": 800000, "max_cost_cny": 5,
                              "input_cny_per_million": 2.1, "output_cny_per_million": 8.4}}
        validate_config(config)
        for key, value in (("max_requests", 9), ("max_cost_cny", 6), ("input_cny_per_million", 0.1)):
            broken = json.loads(json.dumps(config)); broken["budgets"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_config(broken)
        config["sessions"][0]["session_id"] = "other"
        with self.assertRaises(ValueError):
            validate_config(config)

    def test_execute_refuses_to_read_key_when_baseline_infrastructure_fails(self):
        from scripts import run_agent_pilot as runner
        config = {"sessions": [{"session_id": name, "family": name, "max_generated_candidates": 3}
                               for name in ("planning", "symbolic")],
                  "budgets": {"max_requests": 8, "max_requests_per_session": 4,
                              "max_output_tokens": 4096, "max_input_bytes": 98304,
                              "max_reserved_tokens": 800000, "max_cost_cny": 5,
                              "input_cny_per_million": 2.1, "output_cny_per_million": 8.4}}

        class HaltingController(FakeController):
            def __init__(self, *args, **kwargs):
                super().__init__(); self.halted = True

            def baseline(self):
                return {"status": "infrastructure_error"}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); cfg = root / "config.json"; cfg.write_text(json.dumps(config))
            auth = types.ModuleType("configure_minimax")
            auth.CONFIG = root / "unused-model.json"
            auth.auth_path = Mock(side_effect=AssertionError("must not resolve key"))
            auth.read_key = Mock(side_effect=AssertionError("must not read key"))
            with patch.object(runner, "ROOT", root), patch.object(runner, "source_provenance", return_value={}), \
                    patch("rsi_eval.pilot_controller.PilotController", HaltingController), \
                    patch.dict(sys.modules, {"configure_minimax": auth}), \
                    patch.object(sys, "argv", ["run_agent_pilot", "--config", str(cfg), "--run-id", "blocked", "--execute"]), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(), 1)
            auth.auth_path.assert_not_called(); auth.read_key.assert_not_called()
            saved = json.loads((root / "runs/agent-pilot/blocked/summary.json").read_text())
            self.assertEqual(saved["error_type"], "RuntimeError")
            self.assertEqual(saved["budget"]["request_count"], 0)

    def test_actual_agent_round_trip_and_only_allowed_tools(self):
        ledger, controller = FakeLedger(), FakeController()
        responses = [
            ModelResponse(id="r1", model="minimax-m3", choices=[{"message": {
                "role": "assistant", "content": "Test the candidate.", "tool_calls": [{
                    "id": "t1", "type": "function", "function": {"name": "submit_candidate",
                    "arguments": json.dumps({"source": "def get_plan(*args): return []", "rationale": "test"})}}]},
                "finish_reason": "tool_calls"}], usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}),
            ModelResponse(id="r2", model="minimax-m3", choices=[{"message": {"role": "assistant", "content": "Observed ten development successes."}, "finish_reason": "stop"}],
                          usage={"prompt_tokens": 150, "completion_tokens": 10, "total_tokens": 160})]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with patch("openhands.sdk.llm.llm.litellm_completion", side_effect=responses) as transport, \
                    patch("openhands.sdk.conversation.impl.local_conversation.load_available_plugins", side_effect=AssertionError("ambient discovery")), \
                    patch("openhands.sdk.conversation.impl.local_conversation.register_file_agents", side_effect=AssertionError("ambient agents")):
                report = run_session(controller, self.llm(ledger, output / "requests"), "test", output)
            self.assertEqual(report["status"], "completed", report)
            self.assertEqual(report["tools"], ["finish", "submit_candidate"])
            self.assertEqual(len(controller.calls), 1)
            self.assertEqual(transport.call_count, 2)
            self.assertEqual(len(ledger.settlements), 2)
            self.assertEqual(ledger.settlements[0][1]["total_tokens"], 120)
            for call in transport.call_args_list:
                self.assertEqual(call.kwargs["max_retries"], 0)
            saved = "".join(p.read_text() for p in output.rglob("*.json"))
            self.assertNotIn("fake-test-key", saved)

    def test_budget_denial_happens_before_transport(self):
        with tempfile.TemporaryDirectory() as temporary:
            llm = self.llm(FakeLedger(limit=0), Path(temporary))
            with patch("openhands.sdk.llm.llm.litellm_completion") as transport:
                with self.assertRaises(RuntimeError):
                    llm._transport_call(messages=[], max_tokens=4096)
            transport.assert_not_called()

    def test_multiple_candidate_calls_or_finish_mix_never_reach_controller(self):
        for names in (("submit_candidate", "submit_candidate"), ("submit_candidate", "finish")):
            ledger, controller = FakeLedger(), FakeController()
            calls = [{"id": "t" + str(i), "type": "function", "function": {"name": name,
                      "arguments": json.dumps({"source": "pass"})}} for i, name in enumerate(names)]
            response = ModelResponse(id="multi", model="minimax-m3", choices=[{"message": {
                "role": "assistant", "content": None, "tool_calls": calls}, "finish_reason": "tool_calls"}],
                usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120})
            with self.subTest(names=names), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary)
                with patch("openhands.sdk.llm.llm.litellm_completion", return_value=response) as transport:
                    report = run_session(controller, self.llm(ledger, output / "requests"), "test", output)
                self.assertEqual(controller.calls, [])
                self.assertEqual(transport.call_count, 1)
                self.assertEqual(report["status"], "error")
                self.assertEqual(ledger.settlements[0][1]["total_tokens"], 120)
                saved = json.loads((output / "requests/1.response.json").read_text())
                self.assertEqual(len(saved["choices"][0]["message"]["tool_calls"]), 2)
                self.assertEqual(saved["error_type"], "PilotResponseContractError")

    def test_provider_error_is_recorded_without_exception_text_or_secret(self):
        ledger = FakeLedger()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            llm = self.llm(ledger, output)
            with patch("openhands.sdk.llm.llm.litellm_completion", side_effect=RuntimeError("fake-test-key")):
                with self.assertRaises(RuntimeError):
                    llm._transport_call(messages=[], max_tokens=4096)
            self.assertEqual(ledger.settlements, [("1", None, "RuntimeError")])
            saved = "".join(p.read_text() for p in output.glob("*.json"))
            self.assertNotIn("fake-test-key", saved)

    def test_http_error_keeps_only_numeric_status_and_whitelisted_code(self):
        from rsi_eval.pilot_agent import safe_error_metadata
        error = RuntimeError("fake-test-key")
        error.status_code = 503
        error.code = "api_error"
        error.response = types.SimpleNamespace(status_code=500, text="fake-test-key", headers={"key": "fake-test-key"})
        self.assertEqual(safe_error_metadata(error), {"http_status": 503, "error_code": "api_error"})
        error.status_code = "fake-test-key"; error.code = "fake-test-key"
        self.assertEqual(safe_error_metadata(error), {"http_status": 500})
        ledger = FakeLedger()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with patch("openhands.sdk.llm.llm.litellm_completion", side_effect=error), self.assertRaises(RuntimeError):
                self.llm(ledger, output)._transport_call(messages=[], max_tokens=4096)
            saved = (output / "1.response.json").read_text()
            self.assertEqual(json.loads(saved)["http_status"], 500)
            self.assertNotIn("fake-test-key", saved)

    def test_resume_reuses_failed_ledger_without_overwriting_parent_report(self):
        from scripts import run_agent_pilot as runner
        from rsi_eval.pilot_budget import BudgetLedger
        config = {"sessions": [{"session_id": name, "family": name, "max_generated_candidates": 3}
                               for name in ("planning", "symbolic")],
                  "budgets": {"max_requests": 8, "max_requests_per_session": 4,
                              "max_output_tokens": 4096, "max_input_bytes": 98304,
                              "max_reserved_tokens": 800000, "max_cost_cny": 5,
                              "input_cny_per_million": 2.1, "output_cny_per_million": 8.4}}

        class ReadyController(FakeController):
            def __init__(self, *args, **kwargs):
                super().__init__(); self.halted = False

            def baseline(self):
                return {"status": "evaluated"}

        class FakeBoundedLLM:
            def __init__(self, **kwargs):
                pass

            def bind_pilot(self, ledger, session_id, output_dir):
                self.ledger = ledger
                return self

        def fake_run(controller, llm, session_id, output):
            request_id = llm.ledger.reserve(session_id, {"messages": []}, 4096)
            llm.ledger.settle(request_id, {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110})
            return {"session_id": session_id, "status": "completed"}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); cfg = root / "config.json"; cfg.write_text(json.dumps(config))
            old = root / "runs/agent-pilot/failed"; old.mkdir(parents=True)
            ledger = BudgetLedger(old / "budget-ledger.json", **config["budgets"])
            request_id = ledger.reserve("planning", {"messages": []}, 4096)
            ledger.settle(request_id, None, error_type="InternalServerError")
            old_report = {"run_id": "failed", "mode": "execute", "status": "completed_with_stops",
                          "config_sha256": hashlib.sha256(cfg.read_bytes()).hexdigest(),
                          "sessions": [{"session_id": name, "controller": {"generated_candidates": 0}}
                                       for name in ("planning", "symbolic")]}
            (old / "summary.json").write_text(json.dumps(old_report))
            original = (old / "summary.json").read_bytes()
            auth = types.ModuleType("configure_minimax")
            auth.CONFIG = root / "model.json"; auth.CONFIG.write_text(json.dumps({"model": "test", "timeout": 60}))
            auth.auth_path = Mock(return_value="unused")
            auth.read_key = Mock(return_value="fake-test-key")
            with patch.object(runner, "ROOT", root), patch.object(runner, "source_provenance", return_value={}), \
                    patch("rsi_eval.pilot_controller.PilotController", ReadyController), \
                    patch("rsi_eval.pilot_agent.BoundedPilotLLM", FakeBoundedLLM), \
                    patch("rsi_eval.pilot_agent.run_session", side_effect=fake_run), \
                    patch.dict(sys.modules, {"configure_minimax": auth}), \
                    patch.object(sys, "argv", ["run_agent_pilot", "--config", str(cfg), "--run-id", "recovery", "--resume-from", "failed", "--execute"]), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(), 0)
            self.assertEqual((old / "summary.json").read_bytes(), original)
            self.assertFalse((root / "runs/agent-pilot/recovery/budget-ledger.json").exists())
            saved = json.loads((root / "runs/agent-pilot/recovery/summary.json").read_text())
            self.assertEqual(saved["parent_run_id"], "failed")
            self.assertEqual(saved["budget"]["request_count"], 3)
            self.assertEqual(saved["budget"]["failed_count"], 1)
            self.assertEqual(saved["budget"]["session_counts"], {"planning": 2, "symbolic": 1})

    def test_resume_rejects_protocol_change_and_original_run_overwrite(self):
        from scripts import run_agent_pilot as runner
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); old = root / "runs/agent-pilot/failed"; old.mkdir(parents=True)
            (old / "budget-ledger.json").write_text("{}")
            report = {"run_id": "failed", "mode": "execute", "status": "completed_with_stops",
                      "config_sha256": "a", "sessions": [{"session_id": name, "controller": {"generated_candidates": 0}}
                                                           for name in ("planning", "symbolic")]}
            (old / "summary.json").write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                runner.resume_ledger_path(root, "failed", "recovery", "changed")
            with self.assertRaises(ValueError):
                runner.resume_ledger_path(root, "failed", "failed", "a")
            with patch.object(runner, "ROOT", root), \
                    patch.object(sys, "argv", ["runner", "--run-id", "failed", "--resume-from", "failed", "--execute"]), \
                    self.assertRaises(FileExistsError):
                runner.main()
            self.assertEqual(json.loads((old / "summary.json").read_text()), report)


if __name__ == "__main__":
    unittest.main()
