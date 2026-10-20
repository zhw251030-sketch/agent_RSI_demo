"""Offline probe scope/provenance tests; no real candidates run on this host."""
import ast
from collections import Counter
import contextlib
import hashlib
import importlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]
PILOT = Path("artifacts/pilot/2026-10-20")


class DiagnosticProbeTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((PROJECT / "scripts/check_diagnostic_observations.py").is_file(),
                        "Offline diagnostic probe has not been implemented")
        self.probe = importlib.import_module("scripts.check_diagnostic_observations")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.originals = {}
        names = [str(PILOT / (stem + ".py")) for stem in (
            "planning-002", "planning-003", "symbolic-001", "symbolic-002", "symbolic-003")]
        names.append("fixtures/planning/collect_then_tighten.py")
        for relative in names:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            data = (PROJECT / relative).read_bytes()
            path.write_bytes(data)
            self.originals[path] = data
        self.calls, self.feedback = [], []

    def fake_evaluate(self, family, task_id, source, **kwargs):
        self.calls.append((family, task_id, source, kwargs))
        sanity = kwargs["candidate_id"] == "planning-sanity"
        success = sanity or family == "symbolic"
        result = {"schema_version": "0.1", "run_id": "evaluation-%03d" % len(self.calls),
                  "family": family, "task_id": task_id,
                  "candidate_id": kwargs["candidate_id"],
                  "candidate_hash": hashlib.sha256(source.encode()).hexdigest(),
                  "status": "success" if success else "task_failure",
                  "error_kind": None if success else "plan_semantics",
                  "model_calls": 0, "sealed_tasks_executed": 0,
                  "executions": [{"phase": "plan"}] if family == "planning" else
                                [{"phase": "fit"}, {"phase": "predict"}]}
        if family == "symbolic":
            result.update(metrics={"mse": 0.01, "nmse": 0.1}, metric_split="train")
            result["diagnostics"] = {"scope": "train", "candidate_sha256": result["candidate_hash"],
                                     "task_id": task_id, "version": "diagnostics-v0.1",
                                     "residuals": {"status": "ok", "scope": "train", "bias": 0.0,
                                                   "rmse": 0.1, "inputs": []}}
        elif kwargs["diagnostics"]:
            result["diagnostics"] = {"scope": "public_prompt", "candidate_sha256": result["candidate_hash"],
                                     "task_id": task_id, "version": "diagnostics-v0.1",
                                     "trace": {"events_seen": 4, "truncated": False,
                                               "interrupted": False, "lines": [], "functions": []},
                                     "plan_replay": {"status": "valid" if success else "goal_unsatisfied",
                                                     "executed_actions": 0, "plan_length": 0}}
        self.feedback.append(result)
        return result

    def invoke(self, run_id="probe", evaluator=None):
        stream = io.StringIO()
        with patch.object(self.probe, "ROOT", self.root), \
                patch.object(self.probe, "evaluate_candidate", side_effect=evaluator or self.fake_evaluate), \
                contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            code = self.probe.main(["--run-id", run_id])
        path = self.root / "runs/diagnostic-checks" / run_id / "summary.json"
        report = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        return code, report, stream.getvalue()

    def test_named_helpers_only_change_two_index_positions_per_intervention(self):
        for stem, helper_names in (("planning-002", ("_man_location", "_carried_spanner")),
                                   ("planning-003", ("_man_at", "_carrying"))):
            original = (self.root / PILOT / (stem + ".py")).read_bytes().decode()
            variants = self.probe.build_planning_variants(stem, original)
            self.assertEqual([v["variant"] for v in variants], ["original", "at_only", "at_and_carrying"])
            self.assertEqual(variants[0]["source"], original)
            original_lines = original.splitlines(keepends=True)
            tree = ast.parse(original)
            starts = {node.name: node.lineno for node in tree.body if isinstance(node, ast.FunctionDef)}
            expected_changes = {starts[helper_names[0]] + 1, starts[helper_names[0]] + 2}
            for variant, changes in ((variants[1], expected_changes),
                                     (variants[2], expected_changes | {starts[helper_names[1]] + 1,
                                                                      starts[helper_names[1]] + 2})):
                # zero-based comparison: helper's condition is lineno + 1.
                lines = variant["source"].splitlines(keepends=True)
                self.assertEqual(len(lines), len(original_lines))
                self.assertEqual({i for i, (a, b) in enumerate(zip(original_lines, lines)) if a != b}, changes)
                for index in changes:
                    expected = original_lines[index].replace("f[2] == man", "f[1] == man").replace("return f[1]", "return f[2]")
                    self.assertEqual(lines[index], expected)
                self.assertEqual(variant["derivative"], "human_authored_diagnostic_intervention")
                self.assertEqual(variant["parent_source_sha256"], hashlib.sha256(original.encode()).hexdigest())
                self.assertEqual(variant["source_sha256"], hashlib.sha256(variant["source"].encode()).hexdigest())
                self.assertTrue(variant["patch_description"])
                self.assertTrue(variant["patch"])

    def test_missing_modified_or_duplicate_named_helper_is_refused(self):
        original = (self.root / PILOT / "planning-002.py").read_bytes().decode()
        helper = original[original.index("def _man_location"):original.index("\n\ndef _carried_spanner")]
        altered = [original.replace("def _man_location", "def renamed"),
                   original.replace('f[0] == "at"', 'f[0] == "elsewhere"'),
                   original + "\n\n" + helper]
        for source in altered:
            with self.subTest(source=source[-60:]), self.assertRaises(ValueError):
                self.probe.build_planning_variants("planning-002", source)

    def test_fixed_scope_all_results_sources_and_immutability_are_retained(self):
        code, report, _ = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["model_calls"], 0)
        self.assertEqual(report["sealed_tasks_executed"], 0)
        self.assertEqual(report["evaluation_counts"], {"planning": 70, "symbolic": 3})
        self.assertEqual(report["execution_counts"], {"planning": 70, "symbolic": 6})
        planning = [call for call in self.calls if call[0] == "planning"]
        symbolic = [call for call in self.calls if call[0] == "symbolic"]
        self.assertEqual(Counter(call[1] for call in planning),
                         {"spannerlearning/seed0/problem%d" % i: 7 for i in range(10)})
        self.assertEqual([call[1] for call in symbolic], ["oscillator1"] * 3)
        self.assertEqual([call[3]["n_params"] for call in symbolic], [2, 3, 4])
        for family, task_id, _, options in self.calls:
            self.assertEqual(options["root"], self.root)
            self.assertEqual(options["diagnostics"], family == "symbolic" or task_id.endswith(("problem0", "problem1")))
        output = self.root / "runs/diagnostic-checks/probe"
        saved = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((output / "feedback").glob("*.json"))]
        self.assertEqual(saved, self.feedback)
        self.assertEqual(len(report["planning"]), 7)
        self.assertTrue(all(entry["successes"] == 0 for entry in report["planning"][:6]))
        self.assertEqual(report["planning"][-1]["successes"], 10)
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["candidates"]), 10)
        for candidate in manifest["candidates"]:
            raw = (output / candidate["source_file"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), candidate["source_sha256"])
        for path, original in self.originals.items():
            self.assertEqual(path.read_bytes(), original)
        self.assertFalse((self.root / "data").exists())
        self.assertFalse((self.root / "prompts").exists())

    def test_run_id_traversal_and_reserved_windows_names_are_rejected(self):
        for run_id in ("../outside", "a/b", "a\\b", "", ".", "x" * 65, "CON", "nul", "COM1"):
            with self.subTest(run_id=run_id), self.assertRaises(SystemExit) as caught:
                self.invoke(run_id)
            self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.root / "runs").exists())

    def test_existing_output_cannot_be_overwritten(self):
        output = self.root / "runs/diagnostic-checks/probe"
        output.mkdir(parents=True)
        path = output / "summary.json"
        sentinel = b'{"old_result": true}\n'
        path.write_bytes(sentinel)
        code, _, text = self.invoke()
        self.assertEqual(code, 1)
        self.assertIn("FileExistsError", text)
        self.assertEqual(path.read_bytes(), sentinel)
        self.assertEqual(self.calls, [])

    def test_changed_snapshot_is_rejected_before_any_evaluation(self):
        path = self.root / PILOT / "symbolic-002.py"
        path.write_bytes(path.read_bytes() + b"\n# changed\n")
        code, report, _ = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "error")
        self.assertEqual(self.calls, [])

    def test_current_training_manifest_is_in_provenance_without_loading_task_data(self):
        path = self.root / "configs/tasks/downloads-v0.1.json"
        path.parent.mkdir(parents=True)
        path.write_bytes((PROJECT / "configs/tasks/downloads-v0.1.json").read_bytes())
        code, _, _ = self.invoke()
        self.assertEqual(code, 0)
        manifest = json.loads((self.root / "runs/diagnostic-checks/probe/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["trusted_source_sha256"].get("configs/tasks/downloads-v0.1.json"),
                         hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertFalse((self.root / "data").exists())

    def test_missing_misbound_or_nonpublic_diagnostics_cannot_report_completion(self):
        for problem in ("missing", "misbound", "nonpublic", "residual_error"):
            self.calls.clear()
            self.feedback.clear()

            def evaluate(*args, **kwargs):
                result = self.fake_evaluate(*args, **kwargs)
                if len(self.calls) == 1 and problem == "missing":
                    result.pop("diagnostics")
                elif len(self.calls) == 1 and problem == "misbound":
                    result["diagnostics"]["candidate_sha256"] = "0" * 64
                elif len(self.calls) == 3 and problem == "nonpublic":
                    result["diagnostics"] = {"scope": "public_prompt"}
                elif len(self.calls) == 71 and problem == "residual_error":
                    result["diagnostics"]["residuals"] = {"status": "error", "error": "numeric_overflow"}
                return result

            with self.subTest(problem=problem):
                code, report, _ = self.invoke(run_id=problem, evaluator=evaluate)
                self.assertEqual(code, 1)
                self.assertEqual(report["status"], "error")
                self.assertEqual(report["diagnostic_error_count"], 1)
                saved = sorted((self.root / "runs/diagnostic-checks" / problem / "feedback").glob("*.json"))
                self.assertEqual([json.loads(path.read_text(encoding="utf-8")) for path in saved], self.feedback)

    def test_any_infrastructure_failure_is_error_and_all_feedback_is_retained(self):
        def evaluate(*args, **kwargs):
            result = self.fake_evaluate(*args, **kwargs)
            if len(self.calls) == 4:
                result.update(status="infrastructure_error", error_kind="diagnostic_validator_disagreement")
            return result
        code, report, _ = self.invoke(evaluator=evaluate)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "error")
        self.assertEqual(len(self.calls), 73)
        self.assertEqual(report["infrastructure_error_count"], 1)
        saved = sorted((self.root / "runs/diagnostic-checks/probe/feedback").glob("*.json"))
        self.assertEqual(len(saved), 73)
        self.assertEqual(json.loads(saved[3].read_text(encoding="utf-8")), self.feedback[3])

    def test_sanity_failure_is_error_without_demands_on_intervention_success(self):
        def evaluate(*args, **kwargs):
            result = self.fake_evaluate(*args, **kwargs)
            if kwargs["candidate_id"] == "planning-sanity":
                result.update(status="task_failure", error_kind="plan_semantics")
            return result
        code, report, _ = self.invoke(evaluator=evaluate)
        self.assertEqual(code, 1)
        self.assertFalse(report["sanity_passed"])
        self.assertEqual(report["status"], "error")

    def test_executor_exception_is_sanitized_journaled_and_does_not_drop_others(self):
        def evaluate(*args, **kwargs):
            if len(self.calls) == 1:
                self.calls.append((args[0], args[1], args[2], kwargs))
                raise RuntimeError("private-path-or-secret")
            return self.fake_evaluate(*args, **kwargs)
        code, report, text = self.invoke(evaluator=evaluate)
        self.assertEqual(code, 1)
        self.assertEqual(report["evaluation_counts"], {"planning": 70, "symbolic": 3})
        saved = sorted((self.root / "runs/diagnostic-checks/probe/feedback").glob("*.json"))
        self.assertEqual(len(saved), 73)
        self.assertEqual(json.loads(saved[1].read_text(encoding="utf-8"))["error_kind"], "executor_exception")
        self.assertNotIn("private-path-or-secret", text + json.dumps(report) + saved[1].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
