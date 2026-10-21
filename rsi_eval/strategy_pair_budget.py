"""One ordered budget shared by all 36 frozen strategy experiment slots.

Only the legacy constructor's 16-session limit is replaced. Its durable locks,
reservation accounting, usage settlement and summary calculations are reused.
Configured prices are historical estimates, not a provider invoice or quote.
No automatic or operator recovery is supported by this experiment successor.
"""
import hashlib
import json
from pathlib import Path

from .pilot_budget import BudgetExceeded, BudgetLedger

ROOT = Path(__file__).resolve().parents[1]
ALLOCATION = 'configs/pilots/strategy-pair-allocation-v0.1.json'
ALLOCATION_SHA256 = 'f75b2ea2d63c28a4b6e273cd594d1ef92ac4d1847407e36d7f2a81e496d9ea02'


class StrategyPairBudgetLedger(BudgetLedger):
    def __init__(self, path, slot_ids):
        raw = (ROOT / ALLOCATION).read_bytes()
        if hashlib.sha256(raw).hexdigest() != ALLOCATION_SHA256:
            raise ValueError('Frozen 36-slot allocation changed')
        expected = [slot['id'] for slot in json.loads(raw)['slots']]
        if type(slot_ids) is not list or slot_ids != expected:
            raise ValueError('Budget requires all 36 slots in frozen order')
        self.path = Path(path).resolve()
        self.session_ids = tuple(expected)
        self.config = dict(max_requests=36, max_requests_per_session=1,
            max_output_tokens=8192, max_input_bytes=98304,
            max_reserved_tokens=4128768, max_cost_cny=12.0,
            input_cny_per_million=2.1, output_cny_per_million=8.4,
            session_ids=list(expected))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._locked():
            if self.path.exists():
                self._read()
            else:
                self._write(dict(version=1, config=self.config, requests=[],
                                 halted=False, halt_reasons=[]))

    def _read(self):
        state = super()._read()
        rows = state['requests']
        if (len(rows) > 36
                or any(type(row) is not dict for row in rows)
                or [row.get('session_id') for row in rows] != list(self.session_ids[:len(rows)])
                or [row.get('request_id') for row in rows] != [f'request-{i:04d}' for i in range(1, len(rows)+1)]):
            raise ValueError('Persisted request sequence differs from frozen slots')
        return state

    def reserve(self, session_id, request_payload, output_tokens):
        if type(session_id) is not str or session_id not in self.session_ids:
            raise ValueError('Session is not in the frozen strategy allocation')
        with self._locked():
            state = self._read()
            rows = state['requests']
            if len(rows) >= 36 or session_id != self.session_ids[len(rows)]:
                raise BudgetExceeded('Request is not the next frozen slot')
            if any(row['status'] != 'settled' or row['usage_state'] != 'known' for row in rows):
                raise BudgetExceeded('An earlier request is unsettled, failed or usage-unknown')
        # Parent reserve re-locks and rechecks all spending limits. A concurrent
        # contender can only request this same next slot; max_requests_per_session
        # then rejects the second reservation, so no out-of-order slot can pass.
        return super().reserve(session_id, request_payload, output_tokens)

    def resume_after_transport_failure(self):
        raise BudgetExceeded('Strategy experiment does not permit transport recovery')
