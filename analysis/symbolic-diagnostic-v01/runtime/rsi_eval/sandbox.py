"""Run generated Python only inside a Linux namespace and syscall sandbox."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time


def _finite_float(token):
    value = float(token)
    if not math.isfinite(value):
        raise ValueError("nonfinite JSON number")
    return value


def _reject_constant(token):
    raise ValueError("nonfinite JSON constant")


def run_candidate(source: str, request: dict, *, timeout_seconds=20, memory_mb=2048,
                  cpu_seconds=10, max_output_bytes=2000000, deps_dir: Path | None = None) -> dict:
    """Return execution status separately from the task worker's result.

    A completed result is untrusted candidate output, not an authenticated score.
    There is deliberately no direct-execution fallback on unsupported systems.
    """
    started = time.monotonic()
    counts = {"stdout_bytes": 0, "stderr_bytes": 0}

    def outcome(status, **extra):
        return {"status": status, "elapsed_seconds": round(time.monotonic() - started, 6),
                **counts, **extra}

    try:
        encoded = source.encode("utf-8")
        payload = json.dumps(request, allow_nan=False).encode("utf-8")
        if len(encoded) > 65536 or len(payload) > 4 * 1024 * 1024:
            raise ValueError("candidate or request exceeds input limit")
        if request.get("family") not in {"planning", "symbolic"}:
            raise ValueError("unknown task family")
        if not (0 < timeout_seconds <= 300 and 128 <= memory_mb <= 8192
                and 1 <= cpu_seconds <= 300 and 1024 <= max_output_bytes <= 4000000):
            raise ValueError("execution limits outside allowed bounds")
        if sys.platform != "linux" or not shutil.which("bwrap"):
            raise RuntimeError("Linux bubblewrap is required; host execution is disabled")
        if deps_dir is not None and not Path(deps_dir).is_dir():
            raise ValueError("dependency directory does not exist")
    except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
        return outcome("infrastructure_error", error=str(exc))

    package = Path(__file__).resolve().parent
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix="rsi-candidate-") as temporary:
            staging = Path(temporary)
            (staging / "candidate.py").write_bytes(encoded)
            (staging / "request.json").write_bytes(payload)
            command = [shutil.which("bwrap"), "--unshare-all", "--die-with-parent",
                       "--new-session", "--cap-drop", "ALL", "--clearenv"]
            for key, value in {"PATH": "/usr/bin", "LANG": "C.UTF-8", "HOME": "/nonexistent",
                               "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
                               "MKL_NUM_THREADS": "1", "PYTHONDONTWRITEBYTECODE": "1"}.items():
                command += ["--setenv", key, value]
            for directory in ("/usr", "/lib", "/lib64"):
                if Path(directory).exists():
                    command += ["--ro-bind", directory, directory]
            command += ["--proc", "/proc", "--dev", "/dev", "--dir", "/tmp",
                        "--dir", "/runtime", "--ro-bind", str(package), "/runtime/rsi_eval",
                        "--ro-bind", str(staging), "/work"]
            if deps_dir is not None:
                command += ["--ro-bind", str(Path(deps_dir).resolve()), "/deps"]
            command += ["--remount-ro", "/", "--chdir", "/work", "/usr/bin/python3",
                        "-I", "-S", "-B", "/runtime/rsi_eval/worker.py",
                        str(int(memory_mb)), str(int(cpu_seconds))]
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, start_new_session=True, close_fds=True)
            buffers = {"stdout_bytes": bytearray(), "stderr_bytes": bytearray()}
            reason = None
            killed_at = None
            with selectors.DefaultSelector() as selector:
                for name, stream in (("stdout_bytes", process.stdout), ("stderr_bytes", process.stderr)):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, name)
                while selector.get_map():
                    now = time.monotonic()
                    if reason is None and now - started >= timeout_seconds:
                        reason = "timeout"
                    if reason is not None and killed_at is None:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        killed_at = now
                    if reason == "output_limit":
                        break
                    if killed_at is not None and now - killed_at > 1:
                        break
                    for key, _ in selector.select(timeout=0.05):
                        remaining = max_output_bytes - sum(counts.values())
                        chunk = os.read(key.fileobj.fileno(), max(1, min(65536, remaining + 1)))
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        counts[key.data] += len(chunk)
                        buffers[key.data].extend(chunk)
                        if sum(counts.values()) > max_output_bytes:
                            reason = "output_limit"
                            break
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait(timeout=2)
            process.stdout.close()
            process.stderr.close()
            if reason is not None:
                return outcome(reason)
            if process.returncode:
                if process.returncode in (-signal.SIGXCPU, -signal.SIGXFSZ, -signal.SIGKILL,
                                          128 + signal.SIGXCPU, 128 + signal.SIGXFSZ, 128 + signal.SIGKILL):
                    status = "resource_limit"
                elif process.returncode == 70:
                    status = "infrastructure_error"
                elif not buffers["stdout_bytes"] and buffers["stderr_bytes"].startswith(b"bwrap:"):
                    status = "infrastructure_error"
                else:
                    status = "candidate_process_error"
                return outcome(status, returncode=process.returncode,
                               error=buffers["stderr_bytes"].decode("utf-8", "replace")[-1000:])
            try:
                result = json.loads(buffers["stdout_bytes"], parse_float=_finite_float,
                                    parse_constant=_reject_constant)
                if not isinstance(result, dict) or not isinstance(result.get("status"), str):
                    raise ValueError("worker response is not a result object")
            except (ValueError, UnicodeError, RecursionError) as exc:
                return outcome("candidate_process_error", error=f"invalid worker output: {exc}")
            if result["status"] == "resource_limit":
                return outcome("resource_limit", result=result)
            return outcome("completed", result=result)
    except (OSError, subprocess.SubprocessError) as exc:
        return outcome("infrastructure_error", error=f"sandbox launch or transport failed: {exc}")
    finally:
        if process is not None:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
