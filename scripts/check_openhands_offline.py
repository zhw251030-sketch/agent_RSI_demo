"""Check the installed SDK and a fixed TerminalAction without an LLM call.

Run on Linux with the project virtual environment. This is an installation
check, not an Agent rollout, task benchmark, or security sandbox.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shlex
import sys
import tempfile
from datetime import datetime, timezone


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if sys.version_info[:2] != (3, 12) or sys.platform != "linux":
        raise RuntimeError("This pinned environment check requires Linux Python 3.12.")

    versions = {
        name: importlib.metadata.version(name)
        for name in ("openhands-sdk", "openhands-tools", "litellm")
    }
    for name in ("openhands-sdk", "openhands-tools"):
        if versions[name] != "1.55.1":
            raise RuntimeError(f"Unexpected {name} version: {versions[name]}")

    # Avoid the known LiteLLM import-time download of model metadata.
    # The audit hook below observes this Python process, not arbitrary children.
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"
    network_attempts = []

    def deny_python_network(event, _args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            network_attempts.append(event)
            raise RuntimeError("Network access is disabled for this offline check.")

    sys.addaudithook(deny_python_network)
    from openhands.sdk import Agent, Conversation, LLM, Tool  # noqa: F401
    from openhands.tools.terminal import TerminalAction, TerminalExecutor

    (root / "tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="openhands-check-", dir=root / "tmp") as tmp:
        scratch = Path(tmp)
        # The official PTY backend adds -i. Suppress personal shell startup files.
        shell = scratch / "clean-bash"
        shell.write_text('#!/bin/sh\nexec /bin/bash --noprofile --norc "$@"\n')
        shell.chmod(0o700)
        executor = TerminalExecutor(
            working_dir=str(scratch),
            terminal_type="subprocess",
            shell_path=str(shell),
        )
        try:
            payload = (
                "import json; from pathlib import Path; "
                "result={'sum':sum([2,3,5]), 'cwd_ok':Path.cwd().name.startswith('openhands-check-')}; "
                "Path('probe.json').write_text(json.dumps(result)); "
                "print('OPENHANDS_TOOL_OK')"
            )
            command = shlex.join([sys.executable, "-I", "-S", "-c", payload])
            observation = executor(TerminalAction(command=command, timeout=10))
            if observation.exit_code != 0 or observation.timeout or observation.is_error:
                raise RuntimeError("Fixed success command did not complete successfully.")
            if "OPENHANDS_TOOL_OK" not in observation.text:
                raise RuntimeError("Expected tool output marker was not returned.")
            result = json.loads((scratch / "probe.json").read_text())
            if result != {"sum": 10, "cwd_ok": True}:
                raise RuntimeError("Tool file output or working directory was incorrect.")

            failure = executor(TerminalAction(
                command=shlex.join([sys.executable, "-I", "-S", "-c", "raise SystemExit(7)"]),
                timeout=10,
            ))
            if failure.exit_code != 7 or failure.timeout:
                raise RuntimeError("Tool did not preserve the fixed command's nonzero exit code.")
        finally:
            executor.close()

    if network_attempts:
        raise RuntimeError(f"Unexpected Python network attempts: {network_attempts}")
    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "passed",
        "python": platform.python_version(),
        "platform": sys.platform,
        "packages": versions,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "checks": {
            "sdk_and_tools_import": True,
            "terminal_success_exit_code": observation.exit_code,
            "terminal_nonzero_exit_code": failure.exit_code,
            "fixed_file_roundtrip": result,
            "python_network_attempts": network_attempts,
            "terminal_closed": True,
        },
        "llm_objects_constructed": 0,
        "model_calls": 0,
        "agent_rollouts": 0,
        "scope": "Manual fixed commands through the official TerminalExecutor; not an OS sandbox or benchmark.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
