"""Real Linux sandbox acceptance tests; never run candidate code on the host."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from rsi_eval.sandbox import run_candidate


REQUEST = {"family": "planning", "objects": [], "init": [], "goal": []}
EMPTY = "def get_plan(objects, init, goal):\n    return []\n"


class InputBoundaryTests(unittest.TestCase):
    def test_rejects_oversized_source_without_execution(self):
        result = run_candidate("#" * 65537, REQUEST)
        self.assertEqual(result["status"], "infrastructure_error")

    def test_rejects_non_json_request(self):
        result = run_candidate(EMPTY, {"family": "planning", "bad": object()})
        self.assertEqual(result["status"], "infrastructure_error")


@unittest.skipUnless(sys.platform == "linux" and shutil.which("bwrap"), "Linux bubblewrap required")
class SandboxTests(unittest.TestCase):
    def assert_completed(self, source):
        result = run_candidate(source, REQUEST)
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["result"].get("status"), "ok", result)
        return result

    def test_canary_environment_and_network_are_hidden(self):
        with tempfile.TemporaryDirectory() as temp:
            canary = Path(temp) / "private-canary.txt"
            canary.write_text("not candidate input", encoding="utf-8")
            previous = os.environ.get("RSI_SANDBOX_SECRET_CANARY")
            os.environ["RSI_SANDBOX_SECRET_CANARY"] = "not candidate input"
            try:
                self.assert_completed(f'''import os, socket
def get_plan(objects, init, goal):
    assert not os.path.exists({str(canary)!r})
    assert not os.path.exists('/home')
    assert 'RSI_SANDBOX_SECRET_CANARY' not in os.environ
    try:
        socket.socket()
    except PermissionError:
        return []
    raise AssertionError('socket creation permitted')
''')
            finally:
                if previous is None:
                    os.environ.pop("RSI_SANDBOX_SECRET_CANARY", None)
                else:
                    os.environ["RSI_SANDBOX_SECRET_CANARY"] = previous

    def test_process_creation_and_file_writes_are_denied(self):
        self.assert_completed('''import os
def get_plan(objects, init, goal):
    for action in (os.fork, lambda: open('/tmp/created', 'w')):
        try:
            action()
        except PermissionError:
            continue
        raise AssertionError('forbidden operation permitted')
    return []
''')

    def test_wall_timeout_and_recovery(self):
        result = run_candidate("while True: pass", REQUEST, timeout_seconds=0.5)
        self.assertEqual(result["status"], "timeout", result)
        self.assert_completed(EMPTY)

    def test_memory_limit_and_recovery(self):
        result = run_candidate("allocation = bytearray(512 * 1024 * 1024)\n" + EMPTY,
                               REQUEST, memory_mb=128)
        self.assertEqual(result["status"], "resource_limit", result)
        self.assert_completed(EMPTY)

    def test_cpu_limit_and_recovery(self):
        result = run_candidate("while True: pass", REQUEST,
                               cpu_seconds=1, timeout_seconds=5)
        self.assertEqual(result["status"], "resource_limit", result)
        self.assert_completed(EMPTY)

    def test_output_flood_is_bounded(self):
        result = run_candidate("while True: print('x' * 4096, flush=True)", REQUEST,
                               max_output_bytes=16384)
        self.assertEqual(result["status"], "output_limit", result)
        self.assertLessEqual(result["stdout_bytes"] + result["stderr_bytes"], 16385)
        self.assert_completed(EMPTY)

    def test_stdout_forgery_is_not_a_valid_result(self):
        source = "import os\nos.write(1, b'{}\\n')\n" + EMPTY
        result = run_candidate(source, REQUEST)
        self.assertEqual(result["status"], "candidate_process_error", result)


if __name__ == "__main__":
    unittest.main()
