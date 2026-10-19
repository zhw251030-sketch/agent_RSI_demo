#!/usr/bin/env python3
"""Configure Canvas from an existing key file without displaying its contents.

Only sends the key to this project's loopback Canvas API. Configuration itself
does not call a model. The separate smoke script makes two bounded requests.
"""
import argparse
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PROFILE = 'minimax-m3'
CONFIG = Path(os.environ.get('RSI_MODEL_CONFIG', ROOT / 'configs/models/minimax-m3.json'))
LOCAL = ROOT / 'config.local.json'


def read_key(path):
    """The user-supplied auth.json is a single plaintext token, not JSON."""
    value = Path(path).read_text(encoding='utf-8-sig').strip()
    if not value or any(char.isspace() for char in value) or value.startswith(('{', '[')):
        raise ValueError('Expected one non-empty API key token; file content was not printed.')
    return value


def auth_path(explicit=None):
    if explicit:
        return Path(explicit).expanduser().resolve()
    path = os.environ.get('MINIMAX_API_KEY_FILE')
    if path:
        return Path(path).expanduser().resolve()
    if LOCAL.exists():
        value = json.loads(LOCAL.read_text())
        if value.get('minimax_auth_file'):
            return Path(value['minimax_auth_file'])
    raise ValueError('Provide --auth-file or MINIMAX_API_KEY_FILE.')


def request(method, route, body=None):
    session_key = (ROOT / '.canvas-state/agent-canvas/api-key.txt').read_text().strip()
    headers = {'X-Session-API-Key': session_key, 'Content-Type': 'application/json'}
    req = urllib.request.Request('http://127.0.0.1:18080' + route,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        # Validation errors may echo input, including credentials: never dump body.
        raise RuntimeError(f'Canvas {method} {route}: HTTP {error.code}; response body suppressed.') from None


def configure(explicit):
    if LOCAL.is_symlink():
        raise ValueError('Refusing to write machine-local configuration through a symlink.')
    source = auth_path(explicit)
    llm = json.loads(CONFIG.read_text())
    llm['api_key'] = read_key(source)
    existing = request('GET', '/api/profiles')['profiles']
    if any(profile.get('name') == PROFILE for profile in existing):
        current = request('GET', '/api/profiles/' + PROFILE)['config']
        if current.get('model') != llm['model'] or current.get('base_url') != llm['base_url']:
            raise ValueError('Existing profile has a different model/endpoint; refusing to overwrite.')
    request('POST', '/api/profiles/' + PROFILE, {'llm': llm, 'include_secrets': True})
    activated = request('POST', '/api/profiles/' + PROFILE + '/activate')
    settings = request('GET', '/api/settings')
    active_llm = settings['agent_settings'].get('llm', {})
    assert activated['llm_applied'] and settings['active_profile'] == PROFILE
    assert settings['llm_api_key_is_set'] and active_llm['model'] == llm['model']
    assert active_llm['base_url'] == llm['base_url']
    assert active_llm['reasoning_effort'] == 'none'
    assert active_llm['capability_overrides']['supports_reasoning_effort'] is False
    assert active_llm['litellm_extra_body']['thinking']['type'] == 'disabled'
    # Store only a source path, not another plaintext copy of the model key.
    local = json.loads(LOCAL.read_text()) if LOCAL.exists() else {}
    local['minimax_auth_file'] = str(source)
    fd = os.open(LOCAL, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(local, stream, indent=2)
        stream.write('\n')
    LOCAL.chmod(0o600)
    print(json.dumps({'profile': PROFILE, 'model': llm['model'],
                      'base_url': llm['base_url'], 'active': True,
                      'api_key_is_set': True, 'model_requests': 0}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--auth-file', help='Existing plaintext key file; never a key value.')
    args = parser.parse_args()
    try:
        configure(args.auth_file)
    except Exception as error:
        # Fixed error messages above are safe. Avoid arbitrary library exception text.
        print(json.dumps({'ok': False, 'error_type': type(error).__name__}))
        raise SystemExit(1) from None
