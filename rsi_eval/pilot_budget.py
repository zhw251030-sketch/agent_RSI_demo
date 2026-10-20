"""Persistent, fail-closed request budget for the controlled pilot.

The input reservation is compact UTF-8 JSON bytes + 8192, NOT a provider token
count. Costs use configured uncached token prices, NOT an invoice or provider
spending limit. Reservations are never refunded, even when a request fails.
Missing response usage halts later requests, regardless of success or failure.
An operator may explicitly recover once from a recognized transport failure;
that action never refunds reservations or turns unknown usage into zero.

An exclusive-create lock works across processes on Linux and Windows. Lock
contention immediately refuses the operation; a crash can leave a stale lock
that must be inspected manually. The ledger is fsynced and atomically replaced
before reserve() returns, so the caller must call reserve before transport.
"""

import hashlib
import json
import math
import os
import re
import tempfile
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path


class BudgetExceeded(RuntimeError):
    """No request may be sent after this exception."""


class BudgetLedger:
    def __init__(self, path, *, max_requests=8, max_requests_per_session=4,
                 max_output_tokens=4096, max_input_bytes=98304,
                 max_reserved_tokens=800000, max_cost_cny=5,
                 input_cny_per_million=2.1, output_cny_per_million=8.4,
                 session_ids=None):
        self.path = Path(path).resolve()
        self.config = {
            'max_requests': max_requests,
            'max_requests_per_session': max_requests_per_session,
            'max_output_tokens': max_output_tokens,
            'max_input_bytes': max_input_bytes,
            'max_reserved_tokens': max_reserved_tokens,
        }
        if any(type(v) is not int or v <= 0 for v in self.config.values()):
            raise ValueError('integer budget limits must be positive integers')
        for key, value in [('max_cost_cny', max_cost_cny),
                           ('input_cny_per_million', input_cny_per_million),
                           ('output_cny_per_million', output_cny_per_million)]:
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError('cost limits and prices must be finite and positive')
            self.config[key] = float(value)
        self.session_ids = ('planning', 'symbolic')
        if session_ids is not None:
            if (not isinstance(session_ids, list) or not 1 <= len(session_ids) <= 16
                    or any(not isinstance(s, str)
                           or re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', s) is None
                           for s in session_ids)
                    or len(set(session_ids)) != len(session_ids)):
                raise ValueError('session_ids must be a list of 1 to 16 unique ASCII identifiers')
            self.session_ids = tuple(session_ids)
            # Omit this field for the legacy default so existing ledgers reopen.
            self.config['session_ids'] = list(self.session_ids)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._locked():
            if self.path.exists():
                self._read()
            else:
                self._write({'version': 1, 'config': self.config, 'requests': [],
                             'halted': False, 'halt_reasons': []})

    @contextmanager
    def _locked(self):
        lock_path = self.path.with_name(self.path.name + '.lock')
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise BudgetExceeded('budget ledger locked; no request allowed') from exc
        os.close(fd)
        try:
            yield
        finally:
            lock_path.unlink()

    def _read(self):
        state = json.loads(self.path.read_text(encoding='utf-8'))
        if (not isinstance(state, dict) or state.get('version') != 1
                or state.get('config') != self.config):
            raise ValueError('existing ledger configuration mismatch')
        if (not isinstance(state.get('requests'), list)
                or type(state.get('halted')) is not bool
                or not isinstance(state.get('halt_reasons'), list)):
            raise ValueError('invalid budget ledger')
        return state

    def _write(self, state):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                             dir=self.path.parent, delete=False,
                                             prefix=self.path.name + '.', suffix='.tmp') as stream:
                temporary = Path(stream.name)
                json.dump(state, stream, ensure_ascii=False, allow_nan=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            if os.name == 'posix':
                directory = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def _cost(self, input_tokens, output_tokens):
        return (Decimal(input_tokens) * Decimal(str(self.config['input_cny_per_million']))
                + Decimal(output_tokens) * Decimal(str(self.config['output_cny_per_million']))) / 1000000

    def reserve(self, session_id, request_payload, output_tokens):
        if session_id not in self.session_ids:
            raise ValueError('session_id must be in the configured session allowlist')
        if type(output_tokens) is not int or output_tokens <= 0:
            raise ValueError('output_tokens must be a positive integer')
        if output_tokens > self.config['max_output_tokens']:
            raise BudgetExceeded('per-request output token cap exceeded')
        if not isinstance(request_payload, dict):
            raise ValueError('request_payload must be a JSON object')
        payload = json.dumps(request_payload, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')
        if len(payload) > self.config['max_input_bytes']:
            raise BudgetExceeded('input byte cap exceeded')
        input_reservation = len(payload) + 8192
        with self._locked():
            state = self._read()
            requests = state['requests']
            if state['halted']:
                raise BudgetExceeded('budget halted after invalid or excessive usage')
            if len(requests) >= self.config['max_requests']:
                raise BudgetExceeded('total request cap exceeded')
            if sum(r['session_id'] == session_id for r in requests) >= self.config['max_requests_per_session']:
                raise BudgetExceeded('per-session request cap exceeded')
            input_total = sum(r['input_token_reservation'] for r in requests) + input_reservation
            output_total = sum(r['output_token_reservation'] for r in requests) + output_tokens
            if input_total + output_total > self.config['max_reserved_tokens']:
                raise BudgetExceeded('cumulative reserved token cap exceeded')
            if self._cost(input_total, output_total) > Decimal(str(self.config['max_cost_cny'])):
                raise BudgetExceeded('cumulative reserved cost cap exceeded')
            request_id = f'request-{len(requests) + 1:04d}'
            requests.append({
                'request_id': request_id, 'session_id': session_id,
                'input_bytes': len(payload),
                'payload_sha256': hashlib.sha256(payload).hexdigest(),
                'input_token_reservation': input_reservation,
                'output_token_reservation': output_tokens,
                'reserved_cost_cny': float(self._cost(input_reservation, output_tokens)),
                'status': 'reserved', 'usage': None, 'usage_state': 'unknown',
            })
            self._write(state)
            return request_id

    def settle(self, request_id, usage, error_type=None):
        if error_type is not None and (not isinstance(error_type, str)
                                      or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', error_type) is None):
            raise ValueError('error_type must contain only an exception class name')
        fields = ('prompt_tokens', 'completion_tokens', 'total_tokens')
        valid = (isinstance(usage, dict)
                 and all(type(usage.get(k)) is int and 0 <= usage[k] <= 10 ** 12 for k in fields)
                 and usage['total_tokens'] == usage['prompt_tokens'] + usage['completion_tokens'])
        normalized = {k: usage[k] for k in fields} if valid else None
        # Hex avoids Python's decimal-digit conversion limit for invalid huge
        # token counts. Only a digest of malformed/extra metadata is retained.
        digest_usage = ({k: {'invalid_integer_hex': hex(v)}
                        if type(v) is int and abs(v) > 10 ** 12 else v
                        for k, v in usage.items()} if isinstance(usage, dict) else usage)
        digest = hashlib.sha256(json.dumps(digest_usage, sort_keys=True, separators=(',', ':'),
                                           default=lambda v: {'unsupported_type': type(v).__name__}).encode('utf-8')).hexdigest()
        settlement = {'usage': normalized,
                      'usage_state': 'known' if valid else ('unknown' if usage is None else 'invalid'),
                      'usage_sha256': digest, 'error_type': error_type,
                      'status': 'failed' if error_type is not None else 'settled'}
        with self._locked():
            state = self._read()
            request = next((r for r in state['requests'] if r['request_id'] == request_id), None)
            if request is None:
                raise ValueError('unknown request_id')
            if request['status'] != 'reserved':
                if all(request.get(k) == v for k, v in settlement.items()):
                    return
                raise ValueError('request already settled with different usage or error')
            reasons = []
            if usage is None:
                reasons.append('usage_unknown')
            elif not valid:
                reasons.append('invalid_usage')
            if valid:
                if usage['prompt_tokens'] > request['input_token_reservation']:
                    reasons.append('actual_input_exceeds_reservation')
                if usage['completion_tokens'] > request['output_token_reservation']:
                    reasons.append('actual_output_exceeds_cap')
                settlement['actual_estimated_cost_cny'] = float(self._cost(
                    usage['prompt_tokens'], usage['completion_tokens']))
            request.update(settlement)
            if reasons:
                state['halted'] = True
                state['halt_reasons'] = sorted(set(state['halt_reasons'] + reasons))
            self._write(state)

    def resume_after_transport_failure(self):
        """Explicit one-time operator recovery; never call as an automatic retry."""
        allowed = {'InternalServerError', 'APIConnectionError', 'Timeout', 'ReadTimeout'}
        with self._locked():
            state = self._read()
            if (not state['halted'] or state['halt_reasons'] != ['usage_unknown']
                    or state.get('recovery') is not None):
                raise BudgetExceeded('ledger is not eligible for transport recovery')
            unknown = [r for r in state['requests'] if r['usage_state'] != 'known']
            if (not unknown
                    or any(r['status'] == 'reserved' for r in state['requests'])
                    or any(r['usage_state'] != 'unknown' or r['status'] != 'failed'
                           or r.get('error_type') not in allowed for r in unknown)):
                raise BudgetExceeded('unknown usage is not exclusively settled transport failure')
            state['recovery'] = {
                'kind': 'operator_transport_recovery',
                'unknown_request_ids': [r['request_id'] for r in unknown],
            }
            state['halted'] = False
            state['halt_reasons'] = []
            self._write(state)

    def summary(self):
        with self._locked():
            state = self._read()
        requests = state['requests']
        input_reserved = sum(r['input_token_reservation'] for r in requests)
        output_reserved = sum(r['output_token_reservation'] for r in requests)
        known = [r['usage'] for r in requests if r['usage_state'] == 'known']
        unknown = len(requests) - len(known)
        prompt = sum(u['prompt_tokens'] for u in known)
        completion = sum(u['completion_tokens'] for u in known)
        known_cost = float(self._cost(prompt, completion))
        return {
            'config': dict(self.config), 'request_count': len(requests),
            'session_counts': {s: sum(r['session_id'] == s for r in requests)
                               for s in self.session_ids},
            'reserved_count': sum(r['status'] == 'reserved' for r in requests),
            'failed_count': sum(r['status'] == 'failed' for r in requests),
            'reserved_input_tokens': input_reserved,
            'reserved_output_tokens': output_reserved,
            'reserved_tokens': input_reserved + output_reserved,
            'reserved_cost_cny': float(self._cost(input_reserved, output_reserved)),
            'usage_unknown_count': unknown,
            'known_prompt_tokens': prompt, 'known_completion_tokens': completion,
            'known_total_tokens': prompt + completion,
            'known_estimated_cost_cny': known_cost,
            'actual_tokens': None if unknown else prompt + completion,
            'actual_estimated_cost_cny': None if unknown else known_cost,
            'halted': state['halted'], 'halt_reasons': list(state['halt_reasons']),
            'recovery': state.get('recovery'),
            'reservation_method': 'compact_utf8_json_bytes_plus_8192',
            'cost_basis': 'configured_uncached_prices_estimate_not_provider_invoice',
        }
