"""Behavioral checks with synthetic data only; never benchmark test splits."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from rsi_eval.symbolic import prepare_task, score_predictions
from rsi_eval import symbolic_worker


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "symbolic"


class SymbolicHostTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.data = self.root / "data/symbolic/llm-sr/oscillator1/train.csv"
        self.data.parent.mkdir(parents=True)
        self.manifest = self.root / "configs/tasks/downloads-v0.1.json"
        self.manifest.parent.mkdir(parents=True)
        self.set_csv("x,v,a\n1,2,3\n4,5,6\n")

    def set_csv(self, content):
        raw = content.encode("utf-8")
        self.data.write_bytes(raw)
        self.manifest.write_text(json.dumps({"symbolic": {
            "source_name": "LLM-SR", "data_dir": "data/symbolic/llm-sr",
            "files": [{"relative_path": "oscillator1/train.csv",
                       "sha256": hashlib.sha256(raw).hexdigest(),
                       "size": len(raw), "rows": 2,
                       "columns": ["x", "v", "a"]}]}}), encoding="utf-8")

    def test_training_target_is_last_column(self):
        task = prepare_task("oscillator1", self.root)
        self.assertEqual(task["X"], [[1.0, 2.0], [4.0, 5.0]])
        self.assertEqual(task["y"], [3.0, 6.0])
        self.assertEqual(task["input_names"], ["x", "v"])

    def test_rejects_test_split_and_path_requests(self):
        for task_id in ["oscillator1/test_id", "../oscillator1", "bactgrow"]:
            with self.subTest(task_id=task_id), self.assertRaises(ValueError):
                prepare_task(task_id, self.root)

    def test_rejects_modified_training_data(self):
        self.data.write_text("x,v,a\n1,2,9\n4,5,6\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash_mismatch"):
            prepare_task("oscillator1", self.root)

    def test_rejects_nonfinite_training_data_even_when_hash_matches(self):
        self.set_csv("x,v,a\n1,2,nan\n4,5,6\n")
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            prepare_task("oscillator1", self.root)

    def test_rejects_misordered_columns(self):
        self.set_csv("a,v,x\n1,2,3\n4,5,6\n")
        with self.assertRaisesRegex(ValueError, "column"):
            prepare_task("oscillator1", self.root)

    def test_host_recomputes_mse_and_population_variance_nmse(self):
        result = score_predictions([1.0, 3.0], [2.0, 2.0])
        self.assertEqual(result, {"status": "success", "metrics": {"mse": 1.0, "nmse": 1.0}})

    def test_host_rejects_invalid_output_and_zero_variance(self):
        for predictions, error in [([1.0], "invalid_shape"),
                                   ([[1.0], [3.0]], "invalid_dtype"),
                                   ([float("nan"), 3.0], "nonfinite_output"),
                                   ([float("inf"), 3.0], "nonfinite_output"),
                                   ([True, False], "invalid_dtype")]:
            with self.subTest(error=error):
                self.assertEqual(score_predictions([1.0, 3.0], predictions),
                                 {"status": "invalid_output", "error": error})
        self.assertEqual(score_predictions([2.0, 2.0], [2.0, 2.0]),
                         {"status": "invalid_output", "error": "zero_target_variance"})


class SymbolicWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        symbolic_worker.prepare_runtime()

    def source(self, name):
        return (FIXTURES / name).read_text(encoding="utf-8")

    def test_fit_known_linear_target_and_predict_without_y(self):
        # y = 2*x - 3*v + 4; independent points identify all three coefficients.
        X = [[0, 0], [1, 0], [0, 1], [2, 3], [-1, 2]]
        y = [4, 6, 1, -1, -4]
        source = self.source("linear.py")
        fitted = symbolic_worker.run(source, {"phase": "fit", "X": X, "y": y, "n_params": 3})
        self.assertEqual(fitted["status"], "success", fitted)
        for actual, expected in zip(fitted["params"], [2, -3, 4]):
            self.assertAlmostEqual(actual, expected, places=6)
        self.assertNotIn("metrics", fitted)
        self.assertGreater(fitted["candidate_calls"], fitted["nfev"])
        predicted = symbolic_worker.run(source, {"phase": "predict", "X": [[3, 1]],
                                                  "params": fitted["params"]})
        self.assertEqual(predicted["status"], "success", predicted)
        self.assertAlmostEqual(predicted["predictions"][0], 7.0, places=6)

    def test_predict_refuses_target_payload(self):
        result = symbolic_worker.run(self.source("constant.py"),
                                     {"phase": "predict", "X": [[1]], "y": [3], "params": [3]})
        self.assertEqual(result["status"], "invalid_request")

    def test_invalid_candidate_outputs_remain_candidate_failures(self):
        for fixture, error in [("invalid_shape.py", "invalid_shape"), ("nan.py", "nonfinite_output")]:
            with self.subTest(fixture=fixture):
                result = symbolic_worker.run(self.source(fixture),
                                             {"phase": "fit", "X": [[1], [2]], "y": [1, 2], "n_params": 1})
                self.assertEqual(result, {"status": "candidate_error", "error": error})

    def test_candidate_exception_is_sanitized(self):
        source = "def equation(*args):\n    raise ValueError('private arbitrary detail')\n"
        result = symbolic_worker.run(source, {"phase": "predict", "X": [[1]], "params": []})
        self.assertEqual(result, {"status": "candidate_error", "error": "execution_error",
                                  "exception_type": "ValueError", "candidate_line": 2})

    def test_syntax_error_reports_type_and_line_without_message(self):
        result = symbolic_worker.run("def equation(:\n    pass\n",
                                     {"phase": "predict", "X": [[1]], "params": []})
        self.assertEqual(result, {"status": "candidate_error", "error": "execution_error",
                                  "exception_type": "SyntaxError", "candidate_line": 1})

    def test_memory_exhaustion_propagates_to_sandbox_resource_classifier(self):
        for source in ["raise MemoryError()\n",
                       "def equation(*args):\n    raise MemoryError()\n"]:
            for request in [{"phase": "predict", "X": [[1]], "params": []},
                            {"phase": "fit", "X": [[1]], "y": [2], "n_params": 1}]:
                with self.subTest(source=source, phase=request["phase"]), self.assertRaises(MemoryError):
                    symbolic_worker.run(source, request)

    def test_zero_parameter_formula(self):
        source = "def equation(x, params):\n    return 2 * x\n"
        result = symbolic_worker.run(source, {"phase": "fit", "X": [[1], [2]], "y": [2, 4], "n_params": 0})
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(result["params"], [])
        self.assertEqual(result["candidate_calls"], 1)

    def test_parameter_limit_and_nonfinite_request_rejected(self):
        for request in [ {"phase": "fit", "X": [[1]], "y": [2], "n_params": 17},
                         {"phase": "fit", "X": [[float("nan")]], "y": [2], "n_params": 1},
                         {"phase": "fit", "X": [[1], [2]], "y": [2], "n_params": 1}]:
            with self.subTest(request=request):
                result = symbolic_worker.run(self.source("constant.py"), request)
                self.assertEqual(result["status"], "invalid_request", result)


if __name__ == "__main__":
    unittest.main()
