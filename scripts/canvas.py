#!/usr/bin/env python3
"""Manage this project's loopback-only Canvas instance (Linux, Python >=3.12).

Install the pinned npm package and uv as described in docs/operations/canvas.md.
This script never configures a model or submits an agent conversation.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.canvas-runtime'
STATE = ROOT / '.canvas-state'
LAUNCHER = RUNTIME / 'npm/node_modules/@openhands/agent-canvas/bin/agent-canvas.mjs'
RECORD = STATE / 'process.json'
PORTS = {'ingress': 18080, 'agent': 18100, 'automation': 18101,
         'frontend': 18102, 'editor_reserved': 19100}


def identity(pid):
    try:
        proc = Path('/proc') / str(pid)
        command = (proc / 'cmdline').read_bytes().split(b'\0')
        if str(LAUNCHER).encode() not in command:
            return None
        return (proc / 'stat').read_text().rsplit(')', 1)[1].split()[19]
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None


def running():
    if not RECORD.exists():
        return None
    record = json.loads(RECORD.read_text())
    if identity(record['pid']) == record['start_ticks']:
        return record['pid']
    return None


def node_binary():
    candidates = [os.environ.get('CANVAS_NODE'), shutil.which('node')]
    candidates += [str(p) for p in sorted(
        (Path.home() / '.nvm/versions/node').glob('*/bin/node'), reverse=True)]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            result = subprocess.run([candidate, '--version'], capture_output=True, text=True)
            if result.returncode == 0 and int(result.stdout.strip().lstrip('v').split('.')[0]) >= 24:
                return str(Path(candidate).resolve())
    raise SystemExit('Node.js >=24 required; set CANVAS_NODE to its executable.')


def environment(node):
    # Carry basic host identity/locale and network routing, not model credentials
    # or unrelated OpenHands configuration from another running project.
    allowed = ('HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'SSL_CERT_FILE',
               'SSL_CERT_DIR', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
               'http_proxy', 'https_proxy', 'all_proxy')
    env = {k: os.environ[k] for k in allowed if k in os.environ}
    env.update({
        'PATH': f'{Path(node).parent}:{RUNTIME}/tools/bin:/usr/local/bin:/usr/bin:/bin',
        'NO_PROXY': 'localhost,127.0.0.1,::1',
        'no_proxy': 'localhost,127.0.0.1,::1',
        'UV_PYTHON': sys.executable,
        'UV_PYTHON_DOWNLOADS': 'never',
        'UV_CACHE_DIR': str(RUNTIME / 'uv-cache'),
        'UV_TOOL_DIR': str(RUNTIME / 'uv-tools'),
        'UV_DEFAULT_INDEX': 'https://pypi.org/simple',
        'TMPDIR': str(RUNTIME / 'tmp'),
        'OH_CANVAS_SAFE_STATE_DIR': str(STATE / 'agent-canvas'),
        'OH_SESSION_API_KEY_PATH': str(STATE / 'agent-canvas/api-key.txt'),
        'OH_SECRET_KEY_PATH': str(STATE / 'agent-canvas/secret-key.txt'),
        'OH_CANVAS_SAFE_BACKEND_PORT': str(PORTS['agent']),
        'OH_CANVAS_SAFE_AUTOMATION_PORT': str(PORTS['automation']),
        'OH_CANVAS_SAFE_VITE_PORT': str(PORTS['frontend']),
        'OH_AGENT_SERVER_VERSION': '1.56.0',
        'OH_AUTOMATION_VERSION': '1.22.0',
        'VITE_WORKING_DIR': str(ROOT),
        'VITE_DO_NOT_TRACK': '1', 'DO_NOT_TRACK': '1',
        'AGENT_CANVAS_DISABLE_TELEMETRY': '1',
        'VITE_ENABLE_BROWSER_TOOLS': 'false',
        'LITELLM_LOCAL_MODEL_COST_MAP': 'True',
        'OPENHANDS_SUPPRESS_BANNER': '1',
    })
    return env


def status():
    report = {'pid': running(), 'url': 'http://127.0.0.1:18080/', 'http': {}}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for label, path in [('page', '/'), ('agent', '/server_info'), ('ready', '/ready'),
                        ('automation', '/api/automation/health')]:
        try:
            with opener.open('http://127.0.0.1:18080' + path, timeout=4) as response:
                report['http'][label] = response.status
        except urllib.error.HTTPError as error:
            report['http'][label] = error.code
        except Exception as error:
            report['http'][label] = type(error).__name__
    print(json.dumps(report, indent=2))


def start():
    if running():
        status()
        return
    for entry in Path('/proc').iterdir():
        if entry.name.isdigit() and identity(int(entry.name)) is not None:
            raise SystemExit(f'Existing project launcher PID {entry.name} has no valid record; inspect before restarting.')
    if not LAUNCHER.is_file() or not (RUNTIME / 'tools/bin/uvx').is_file():
        raise SystemExit('Install Canvas and uv first; see docs/operations/canvas.md.')
    for name, port in PORTS.items():
        with socket.socket() as sock:
            try:
                # Match the launcher's listener semantics: TIME_WAIT sockets
                # after a clean stop must not be mistaken for live services.
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(('127.0.0.1', port))
                sock.listen(1)
            except OSError:
                raise SystemExit(f'{name} port {port} is busy; no service was stopped.')
    STATE.mkdir(mode=0o700, exist_ok=True)
    STATE.chmod(0o700)
    (RUNTIME / 'tmp').mkdir(parents=True, exist_ok=True)
    node = node_binary()
    with (STATE / 'launcher.log').open('ab') as log:
        process = subprocess.Popen(
            [node, str(LAUNCHER), '--host', '127.0.0.1', '--port', str(PORTS['ingress'])],
            cwd=ROOT, env=environment(node), stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True, umask=0o077)
    ticks = None
    for _ in range(40):
        ticks = identity(process.pid)
        if ticks is not None or process.poll() is not None:
            break
        time.sleep(0.05)
    if ticks is None:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        raise SystemExit('Launcher exited; inspect the private launcher.log.')
    RECORD.write_text(json.dumps({'pid': process.pid, 'start_ticks': ticks}) + '\n')
    print(f'Started PID {process.pid}; backend preparation may take several minutes.')
    print('Run status to check readiness. Logs: .canvas-state/launcher.log (private).')


def stop():
    pid = running()
    if pid is None:
        print('No matching managed Canvas process. No other process was signalled.')
        return
    if os.getpgid(pid) != pid:
        raise SystemExit('Unexpected process group; refusing to signal.')
    os.killpg(pid, signal.SIGTERM)
    for _ in range(40):
        if identity(pid) is None:
            RECORD.unlink(missing_ok=True)
            print('Canvas launcher stopped; verify status before restarting.')
            return
        time.sleep(0.25)
    raise SystemExit('Graceful shutdown still pending; no forced kill was issued.')


if __name__ == '__main__':
    if sys.platform != 'linux' or sys.version_info < (3, 12):
        raise SystemExit('Run on the Linux server using .venv/bin/python (>=3.12).')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start', 'stop', 'status'))
    args = parser.parse_args()
    import fcntl
    STATE.mkdir(mode=0o700, exist_ok=True)
    with (STATE / 'manager.lock').open('a') as manager_lock:
        try:
            fcntl.flock(manager_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another Canvas management command is running; retry shortly.')
        {'start': start, 'stop': stop, 'status': status}[args.action]()
