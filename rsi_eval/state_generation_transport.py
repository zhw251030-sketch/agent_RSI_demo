"""Observe one SDK-to-LiteLLM call without logging credentials or arbitrary kwargs.

The request receipt binds already-persisted request bytes and the actual timeout
and retry arguments seen at the callable boundary. It is trusted-process evidence,
not an HTTP trace or provider attestation. No candidate is evaluated here.
"""
from contextlib import contextmanager
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from unittest.mock import patch

VERSION = 'state-generation-transport-v0.1'
_OBSERVER_LOCK = threading.Lock()


def _safe_path(path):
    path = Path(path)
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
           for p in (path, *path.parents)):
        raise ValueError('Symlinked transport record path')
    return path


def _write_once(path, value):
    path = _safe_path(path)
    raw = (json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':'))+'\n').encode('utf-8')
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def _request_binding(directory):
    requests = _safe_path(directory/'requests')
    if not requests.is_dir():
        raise ValueError('Missing persisted request directory')
    files = list(requests.glob('*.request.json'))
    if len(files) != 1:
        raise ValueError('Exactly one persisted request is required')
    path = _safe_path(files[0])
    if not path.is_file() or re.fullmatch(r'request-\d{4}\.request\.json', path.name) is None:
        raise ValueError('Invalid persisted request file')
    return path.relative_to(directory).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()


def _flags(kwargs, expected_timeout):
    timeout = kwargs.get('timeout')
    if (type(timeout) not in (int, float) or not math.isfinite(timeout)
            or timeout != expected_timeout):
        raise ValueError('Actual provider timeout differs from the frozen limit')
    if type(kwargs.get('max_retries')) is not int or kwargs['max_retries'] != 0:
        raise ValueError('Actual provider max_retries must be explicit integer zero')
    if 'num_retries' in kwargs and (type(kwargs['num_retries']) is not int or kwargs['num_retries'] != 0):
        raise ValueError('Actual provider num_retries must be absent or integer zero')
    if 'stream' in kwargs and kwargs['stream'] is not False:
        raise ValueError('Streaming must be absent or false')
    return dict(expected_timeout_seconds=expected_timeout, timeout_seconds=timeout,
                max_retries=0, stream_present='stream' in kwargs, stream=False,
                num_retries_present='num_retries' in kwargs, num_retries=kwargs.get('num_retries'))


@contextmanager
def observed_transport(directory, expected_timeout=180):
    """Observe at most one actual synchronous SDK provider dispatch in this scope.

    Create-only transport-request.json is fsynced before calling the original
    provider; transport-result.json records monotonic elapsed time and a safe
    exception class only. Invalid arguments create no receipt and make no call.
    No call also creates no receipt. Nested/concurrent scopes are rejected because
    SDK 1.55.1 exposes this transport callable as a process-global module binding.
    The caller must retain SDK num_retries=0 and its normal budget/usage guards.
    """
    if type(expected_timeout) is not int or expected_timeout != 180:
        raise ValueError('This frozen observer requires expected_timeout=180')
    directory = _safe_path(directory)
    if not directory.is_dir():
        raise ValueError('Transport session directory does not exist')
    request_receipt = _safe_path(directory/'transport-request.json')
    result_receipt = _safe_path(directory/'transport-result.json')
    if request_receipt.exists() or result_receipt.exists():
        raise FileExistsError('Refusing to overwrite transport receipts')
    if not _OBSERVER_LOCK.acquire(blocking=False):
        raise RuntimeError('A transport observer is already active')
    try:
        module = importlib.import_module('openhands.sdk.llm.llm')
        provider = module.litellm_completion
        attempted = False

        def observe(*args, **kwargs):
            nonlocal attempted
            if attempted:
                raise RuntimeError('A second provider dispatch is forbidden')
            attempted = True
            if args:
                raise ValueError('SDK transport must pass keyword arguments')
            fields = _flags(kwargs, expected_timeout)
            name, digest = _request_binding(directory)
            receipt_hash = _write_once(request_receipt, dict(version=VERSION, **fields,
                request_file=name, request_sha256=digest))
            started = time.monotonic()
            status = 'returned'
            error_type = None
            try:
                return provider(**kwargs)
            except BaseException as error:
                status = 'raised'
                candidate = type(error).__name__
                error_type = candidate if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', candidate) else 'Exception'
                raise
            finally:
                elapsed = time.monotonic() - started
                if not math.isfinite(elapsed) or elapsed < 0:
                    raise RuntimeError('Invalid monotonic transport interval')
                _write_once(result_receipt, dict(version=VERSION,
                    request_receipt_sha256=receipt_hash, elapsed_seconds=elapsed,
                    status=status, error_type=error_type))

        with patch.object(module, 'litellm_completion', observe):
            yield
    finally:
        _OBSERVER_LOCK.release()
