"""Runner boundary tests without credentials, model calls, or task execution."""
import contextlib
import copy
import hashlib
import importlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]
ORDER = [
    {"family": "planning", "arm": "A", "session_id": "planning_A"},
    {"family": "symbolic", "arm": "C", "session_id": "symbolic_C"},
    {"family": "planning", "arm": "B", "session_id": "planning_B"},
    {"family": "symbolic", "arm": "A", "session_id": "symbolic_A"},
    {"family": "planning", "arm": "C", "session_id": "planning_C"},
    {"family": "symbolic", "arm": "B", "session_id": "symbolic_B"},
]


def comparison_config():
    return {
        "schema_version": "0.1",
        "base_config": "configs/pilots/development-v0.1.json",
        "order": copy.deepcopy(ORDER),
        "policy_files": {"A": "prompts/diagnostic/ordinary.md",
                         "B": "prompts/diagnostic/ordinary.md",
                         "C": "prompts/diagnostic/evidence.md"},
        "budgets": {"max_requests": 24, "max_requests_per_session": 4,
                    "max_output_tokens": 4096, "max_input_bytes": 98304,
                    "max_reserved_tokens": 3000000, "max_cost_cny": 10,
                    "input_cny_per_million": 2.1, "output_cny_per_million": 8.4},
    }


class DiagnosticRunnerTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((PROJECT / "scripts/run_diagnostic_comparison.py").is_file(),
                        "The comparison runner must implement the frozen six-session protocol")
        self.runner = importlib.import_module("scripts.run_diagnostic_comparison")
        self.real_source_provenance = self.runner.source_provenance
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = comparison_config()
        self.config_path = self.root / "configs/pilots/diagnostic-comparison-v0.1.json"
        self.config_path.parent.mkdir(parents=True)
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        base = json.loads((PROJECT / "configs/pilots/development-v0.1.json").read_text(encoding="utf-8"))
        self.base = base
        for name in ["configs/pilots/development-v0.1.json", "configs/models/minimax-m3.json"] + [
                item["initial_candidate"] for item in base["sessions"]]:
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((PROJECT / name).read_bytes())
        for name, content in [("ordinary.md", "Revise based on observed feedback."),
                              ("evidence.md", "State a falsifiable prediction and cite observations.")]:
            destination = self.root / "prompts/diagnostic" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        self.events = []
        self.controllers = []
        self.digest_mismatch = False
        self.baseline_halted = False
        self.session_behavior = None
        test = self

        class Controller:
            def __init__(self, root, session_config, output_dir, *, arm, policy_text):
                self.family = session_config["family"]
                self.config = session_config
                self.arm = arm
                self.output_dir = Path(output_dir)
                self.output_dir.mkdir(parents=True)
                self.halted = test.baseline_halted
                self.policy_text = policy_text
                test.controllers.append(self)

            def baseline(self):
                test.events.append(("baseline", self.family, self.arm))
                return {"source_sha256": self.config["initial_candidate_sha256"],
                        "status": "infrastructure_error" if self.halted else "evaluated",
                        "metrics": {"nmse": 1.0} if self.family == "symbolic" else {"total_successes": 0}}

            def task_prompt(self):
                test.events.append(("prompt", self.family, self.arm))
                return self.family + "\n" + self.policy_text

            def initial_observation_digest(self):
                if test.digest_mismatch and self.arm == "C":
                    return "f" * 64
                return ("a" if self.family == "planning" else "b") * 64

            def summary(self):
                return {"family": self.family, "halted": self.halted,
                        "generated_candidates": 0, "sealed_tasks_executed": 0}

        class LLM:
            def __init__(self, **configuration):
                self.configuration = configuration

            def bind_pilot(self, ledger, session_id, output_dir):
                self.ledger, self.session_id = ledger, session_id
                return self

        def run_session(controller, llm, session_id, output_dir):
            test.events.append(("run", session_id))
            if test.session_behavior:
                return test.session_behavior(controller, llm, session_id, output_dir)
            request_id = llm.ledger.reserve(session_id, {"messages": ["fixture"]}, 16)
            llm.ledger.settle(request_id, {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5})
            return {"session_id": session_id, "status": "completed", "model_error_type": None,
                    "conversation_status": "ConversationExecutionStatus.FINISHED",
                    "controller": controller.summary()}

        def read_key(path):
            if len([event for event in test.events if event[0] == "prompt"]) != 6:
                raise AssertionError("Credential access occurred before all six task prompts")
            test.events.append(("read_key",))
            return "fixture-secret-token"

        controller_module = types.ModuleType("rsi_eval.diagnostic_controller")
        controller_module.DiagnosticController = Controller
        self.fake_controller = Controller
        agent_module = types.ModuleType("rsi_eval.pilot_agent")
        agent_module.BoundedPilotLLM, agent_module.run_session = LLM, run_session
        auth_module = types.ModuleType("scripts.configure_minimax")
        self.fake_auth = auth_module
        auth_module.CONFIG = self.root / "configs/models/minimax-m3.json"
        auth_module.auth_path = lambda explicit=None: self.root / "unused-auth.txt"
        auth_module.read_key = read_key
        self.addCleanup(patch.stopall)
        patch.object(self.runner, "ROOT", self.root).start()
        patch.object(self.runner, "source_provenance", return_value={"code_commit": "fixture",
                     "source_sha256": {}, "sdk_version": "1.55.1"}).start()
        patch.dict("sys.modules", {"rsi_eval.diagnostic_controller": controller_module,
                                  "rsi_eval.pilot_agent": agent_module,
                                  "scripts.configure_minimax": auth_module}).start()

    def invoke(self, mode="--prepare-only", run_id="test", extra=()):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            code = self.runner.main(["--config", str(self.config_path), "--run-id", run_id, mode, *extra])
        path = self.root / "runs/diagnostic-comparison" / run_id / "summary.json"
        report = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        return code, report, stream.getvalue()

    def test_fixed_order_and_budget_accepted(self):
        order, budgets = self.runner.validate_config(self.config)
        self.assertEqual([item["session_id"] for item in order],
                         ["planning_A", "symbolic_C", "planning_B", "symbolic_A", "planning_C", "symbolic_B"])
        self.assertEqual(budgets["max_requests"], 24)

    def test_duplicate_reordered_missing_and_mismatched_conditions_rejected(self):
        orders = [ORDER[:-1], ORDER + [ORDER[0]], [ORDER[0]] * 6,
                  [ORDER[1], ORDER[0], *ORDER[2:]]]
        mismatch = copy.deepcopy(ORDER)
        mismatch[0]["family"] = "symbolic"
        orders.append(mismatch)
        for order in orders:
            config = copy.deepcopy(self.config)
            config["order"] = order
            with self.subTest(order=order), self.assertRaises(ValueError):
                self.runner.validate_config(config)

    def test_budget_expansion_nonfinite_numbers_and_wrong_policy_are_rejected(self):
        changes = [("max_requests", 25), ("max_requests_per_session", 5),
                   ("max_output_tokens", 4097), ("max_input_bytes", 98305),
                   ("max_reserved_tokens", 3000001), ("max_cost_cny", 10.01),
                   ("max_cost_cny", float("nan")), ("input_cny_per_million", float("inf")),
                   ("input_cny_per_million", 2), ("output_cny_per_million", 8),
                   ("max_requests", True), ("max_requests", 0)]
        for key, value in changes:
            config = copy.deepcopy(self.config)
            config["budgets"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.runner.validate_config(config)
        for name, value in [("base_config", "../outside.json"), ("schema_version", "2")]:
            config = copy.deepcopy(self.config)
            config[name] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.runner.validate_config(config)
        config = copy.deepcopy(self.config)
        config["policy_files"]["B"] = "prompts/diagnostic/evidence.md"
        with self.assertRaises(ValueError):
            self.runner.validate_config(config)

    def test_prepare_evaluates_all_baselines_without_credential_access(self):
        code, report, _ = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "prepared")
        self.assertEqual(report["budget"]["request_count"], 0)
        self.assertEqual(len([e for e in self.events if e[0] == "baseline"]), 6)
        self.assertNotIn(("read_key",), self.events)
        self.assertFalse(any(event[0] == "run" for event in self.events))
        self.assertEqual(report["config_sha256"], hashlib.sha256(self.config_path.read_bytes()).hexdigest())
        self.assertEqual(len(report["sessions"]), 6)
        for session in report["sessions"]:
            self.assertEqual(len(session["task_prompt_sha256"]), 64)
            self.assertEqual(len(session["initial_observation_sha256"]), 64)
        self.assertNotIn("api_key", report["effective_model_config"])
        self.assertEqual(report["effective_model_config"]["num_retries"], 0)

    def test_observation_mismatch_and_baseline_failure_abort_before_key(self):
        for attribute in ("digest_mismatch", "baseline_halted"):
            with self.subTest(attribute=attribute):
                setattr(self, attribute, True)
                code, report, _ = self.invoke("--execute", run_id=attribute)
                self.assertEqual(code, 1)
                self.assertEqual(report["status"], "error")
                self.assertEqual(report["budget"]["request_count"], 0)
                self.assertNotIn(("read_key",), self.events)
                setattr(self, attribute, False)
                self.events.clear()

    def test_modified_initial_source_aborts_before_evaluation_or_key(self):
        (self.root / self.base["sessions"][0]["initial_candidate"]).write_text("changed", encoding="utf-8")
        code, report, _ = self.invoke("--execute")
        self.assertEqual(code, 1)
        self.assertEqual(report["error_type"], "ValueError")
        self.assertEqual(self.events, [])

    def test_preparation_exception_still_records_all_six_unstarted_conditions(self):
        with patch.object(self.fake_controller, "baseline",
                   side_effect=RuntimeError("fixture-secret-token")):
            code, report, output = self.invoke("--execute")
        self.assertEqual(code, 1)
        self.assertEqual([item["session_id"] for item in report["sessions"]],
                         [item["session_id"] for item in ORDER])
        self.assertEqual([item["status"] for item in report["sessions"]],
                         ["not_started_after_stop"] * 6)
        self.assertNotIn(("read_key",), self.events)
        self.assertNotIn("fixture-secret-token", output + json.dumps(report))

    def test_model_override_or_credential_field_rejected_before_key_and_report_copy(self):
        with patch.object(self.fake_auth, "CONFIG", self.root / "outside.json"):
            code, report, _ = self.invoke("--execute", run_id="override")
        self.assertEqual(code, 1)
        self.assertEqual(report["error_type"], "ValueError")
        path = self.root / "configs/models/minimax-m3.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config["api_key"] = "fixture-secret-token"
        path.write_text(json.dumps(config), encoding="utf-8")
        code, report, output = self.invoke("--execute", run_id="credential")
        self.assertEqual(code, 1)
        self.assertNotIn("model_config", report)
        self.assertNotIn("fixture-secret-token", output + json.dumps(report))
        self.assertNotIn(("read_key",), self.events)

    def test_source_provenance_includes_both_diagnostic_policy_files(self):
        with patch.object(self.runner.importlib.metadata, "version", return_value="1.55.1"), \
                patch.object(self.runner.subprocess, "run", return_value=types.SimpleNamespace(stdout="commit\n")):
            provenance = self.real_source_provenance()
        for name in ("ordinary.md", "evidence.md"):
            relative = "prompts/diagnostic/" + name
            expected = hashlib.sha256((self.root / relative).read_bytes()).hexdigest()
            self.assertEqual(provenance["source_sha256"][relative], expected)

    def test_existing_run_is_preserved_and_resume_flag_is_unsupported(self):
        directory = self.root / "runs/diagnostic-comparison/test"
        directory.mkdir(parents=True)
        original = '{"sentinel": true}\n'
        (directory / "summary.json").write_text(original, encoding="utf-8")
        code, _, output = self.invoke("--execute")
        self.assertEqual(code, 1)
        self.assertIn("FileExistsError", output)
        self.assertEqual((directory / "summary.json").read_text(encoding="utf-8"), original)
        self.assertEqual(self.events, [])
        with self.assertRaises(SystemExit) as caught:
            self.invoke("--execute", run_id="retry", extra=("--resume-from", "test"))
        self.assertEqual(caught.exception.code, 2)
        self.assertFalse((directory.parent / "retry").exists())

    def test_execute_keeps_shared_ledger_and_all_six_distinct_session_ids(self):
        code, report, output = self.invoke("--execute")
        self.assertEqual(code, 0)
        self.assertEqual(report["budget"]["request_count"], 6)
        self.assertEqual(report["budget"]["session_counts"], {item["session_id"]: 1 for item in ORDER})
        self.assertEqual([e[1] for e in self.events if e[0] == "run"], [item["session_id"] for item in ORDER])
        self.assertEqual(len([e for e in self.events if e[0] == "read_key"]), 1)
        self.assertNotIn("fixture-secret-token", output)
        for path in (self.root / "runs").rglob("*.json"):
            self.assertNotIn("fixture-secret-token", path.read_text(encoding="utf-8"))

    def test_normal_iteration_stop_is_preserved_and_later_sessions_run(self):
        def stopped(controller, llm, session_id, directory):
            return {"session_id": session_id, "status": "stopped", "model_error_type": None,
                    "conversation_status": "ConversationExecutionStatus.PAUSED",
                    "controller": controller.summary()}
        self.session_behavior = stopped
        code, report, _ = self.invoke("--execute")
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "completed_with_stops")
        self.assertEqual([item["status"] for item in report["sessions"]], ["stopped"] * 6)
        self.assertEqual(len([e for e in self.events if e[0] == "run"]), 6)

    def test_returned_provider_error_stops_remaining_sessions_without_retry(self):
        def failure(controller, llm, session_id, directory):
            return {"session_id": session_id, "status": "error", "model_error_type": "ProviderError",
                    "controller": controller.summary()}
        self.session_behavior = failure
        code, report, _ = self.invoke("--execute")
        self.assertEqual(code, 1)
        self.assertEqual(report["sessions"][0]["model_error_type"], "ProviderError")
        self.assertEqual([item["status"] for item in report["sessions"]][1:], ["not_started_after_stop"] * 5)
        self.assertEqual(len([e for e in self.events if e[0] == "run"]), 1)

    def test_thrown_exception_is_sanitized_and_remaining_sessions_are_recorded(self):
        def failure(*args):
            print("provider echoed fixture-secret-token")
            raise RuntimeError("fixture-secret-token")
        self.session_behavior = failure
        code, report, output = self.invoke("--execute")
        self.assertEqual(code, 1)
        self.assertEqual(report["sessions"][0]["model_error_type"], "RuntimeError")
        self.assertEqual([item["status"] for item in report["sessions"]][1:], ["not_started_after_stop"] * 5)
        self.assertNotIn("fixture-secret-token", output + json.dumps(report))

    def test_unknown_usage_halts_even_if_session_returns_completed(self):
        def missing_usage(controller, llm, session_id, directory):
            request_id = llm.ledger.reserve(session_id, {}, 16)
            llm.ledger.settle(request_id, None)
            return {"session_id": session_id, "status": "completed", "model_error_type": None,
                    "controller": controller.summary()}
        self.session_behavior = missing_usage
        code, report, _ = self.invoke("--execute")
        self.assertEqual(code, 1)
        self.assertTrue(report["budget"]["halted"])
        self.assertEqual(report["budget"]["request_count"], 1)
        self.assertEqual([item["status"] for item in report["sessions"]][1:], ["not_started_after_stop"] * 5)

    def test_controller_infrastructure_failure_stops_after_current_session(self):
        def infrastructure_failure(controller, llm, session_id, directory):
            controller.halted = True
            return {"session_id": session_id, "status": "completed", "model_error_type": None,
                    "controller": controller.summary()}
        self.session_behavior = infrastructure_failure
        code, report, _ = self.invoke("--execute")
        self.assertEqual(code, 1)
        self.assertTrue(report["sessions"][0]["controller"]["halted"])
        self.assertEqual([item["status"] for item in report["sessions"]][1:], ["not_started_after_stop"] * 5)


if __name__ == "__main__":
    unittest.main()
