import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from analysis.basis_edit_comparison.runner import run_pilot, synthetic_evaluate
from extensions.symbolic_basis_v01.contract import compile_submission
from extensions.basis_trial_v02 import sdk_controller

try:
    SDK = importlib.util.find_spec("openhands.sdk") is not None
except ModuleNotFoundError:
    SDK = False


def provider_for_protocol():
    protocol = json.loads(Path("docs/experiments/2026-10-24-edit-check-comparison-design/protocol.json").read_bytes())
    responses = []
    for slot in protocol["slots"]:
        parent = protocol["parents"][slot["parent_id"]]["feature_ids"]
        features = parent if slot["repeat"] == 1 else parent[:-1] + ["m_0_2_0"]
        responses.append({"tool": "submit_basis", "arguments": {"feature_ids": features}})
    return sdk_controller.FakeProvider(responses)


def fake_session(root, output, session_id, packet, ledger, settings, *, stage, spec):
    request_id = ledger.reserve(session_id, packet, 8192)
    ledger.settle(request_id, {"prompt_tokens": 100, "completion_tokens": 20,
                               "total_tokens": 120})
    features = packet["parent"]["feature_ids"]
    if session_id.endswith("-r2"):
        features = features[:-1] + ["m_0_2_0"]
    compiled = compile_submission({"feature_ids": features, "explanation": "host"}, spec)
    return {"status": "accepted", "business": {"feature_ids": compiled["feature_ids"]},
            "execution_payload": {"feature_ids": compiled["feature_ids"], "explanation": "host"},
            "compiled": compiled}


class BasisEditRunnerTests(unittest.TestCase):
    def test_simulated_runner_freezes_before_shadow_scoring(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = sdk_controller.public_settings() | {"api_key": "synthetic-no-network-key"}
            result = run_pilot(root, root / "pilot", settings=settings,
                               evaluate=synthetic_evaluate, session_runner=fake_session)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["model_requests"], 6)
            self.assertEqual(result["candidate_count"], 6)
            self.assertEqual(result["gate_record_count"], 18)
            self.assertTrue((root / "pilot/gate-freeze.json").is_file())
            self.assertTrue((root / "pilot/shadow-outcomes.json").is_file())
            self.assertFalse(result["sealed_data_read"])

    @unittest.skipUnless(SDK, "Requires OpenHands SDK 1.55.1")
    def test_actual_sdk_fake_provider_runs_the_same_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = provider_for_protocol()
            settings = sdk_controller.public_settings() | {"api_key": "synthetic-no-network-key"}
            result = run_pilot(root, root / "pilot", settings=settings,
                               evaluate=synthetic_evaluate, provider=provider)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["model_requests"], 6)
            self.assertEqual(result["gate_record_count"], 18)
            self.assertEqual(provider.calls, 6)


if __name__ == "__main__":
    unittest.main()
