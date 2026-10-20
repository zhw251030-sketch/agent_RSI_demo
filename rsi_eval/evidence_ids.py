"""Trusted, exact short handles for an explicitly visible evidence snapshot.

This is a transport adapter for ``evidence_checks``, not a new checker. The
controller creates a fresh registry from the evidence it currently authorizes
and persists its manifest before execution. A handle binds all seven reference
fields; it grants no access to snapshots omitted from that registry. No global
lookup, approximate matching, natural-language interpretation or repair occurs.

The 64-bit digest prefix keeps references short. It is not an authentication
token or an assurance that collisions are impossible: each registry checks for
collisions and refuses construction rather than overwriting an exact binding.
Full references remain in host-side expansions/reports/manifests. Only entries()
is intended for model display. Authorizing task scopes remains the caller's job.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re

from . import evidence_checks as checks


VERSION = 'evidence-ids-v0.1'
_ID = re.compile(r'e_[0-9a-f]{16}\Z')
_CLAIM_KEYS = frozenset({'evidence_id', 'op', 'value'})
_PREDICTION_KEYS = frozenset({'evidence_id', 'direction', 'min_delta'})


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':'))


def _reference_id(reference):
    return 'e_' + hashlib.sha256(_canonical(reference).encode('utf-8')).hexdigest()[:16]


def _identifier(value):
    return type(value) is str and len(value) == 18 and _ID.fullmatch(value) is not None


def _invalid(reason):
    return {'status': 'schema_invalid', 'reason': reason}


class EvidenceRegistry:
    """Immutable-by-copy registry for one session and its current visible data.

    Invalid trusted input raises ValueError before any display or lookup.
    Malformed model declarations instead produce bounded schema_invalid reports;
    a well-formed but unknown/stale ID yields unavailable/reference_not_found.
    Public return values are copies, so callers cannot mutate later decisions.
    """

    def __init__(self, snapshots, *, session_id):
        # Reuse exactly the checker's bounded snapshot grammar. Extra host-side
        # restrictions make one ID unambiguous before it reaches the model.
        if not checks._text(session_id) or not checks._snapshots(snapshots):
            raise ValueError('Invalid evidence registry snapshots or session')
        self._session_id = session_id
        self._snapshots = copy.deepcopy(snapshots)
        self._entries = {}
        seen_bindings = set()
        candidate_hashes = {}
        for snapshot in self._snapshots:
            binding = snapshot['binding']
            if binding['session_id'] != session_id or binding['version'] != checks.VERSION:
                raise ValueError('Registry session or evidence version mismatch')
            encoded_binding = _canonical(binding)
            if encoded_binding in seen_bindings:
                raise ValueError('Duplicate evidence binding')
            seen_bindings.add(encoded_binding)
            candidate_id, digest = binding['candidate_id'], binding['candidate_sha256']
            if candidate_id in candidate_hashes and candidate_hashes[candidate_id] != digest:
                raise ValueError('Candidate identity has conflicting source hashes')
            candidate_hashes[candidate_id] = digest
            if snapshot['scalars'].keys() & snapshot['facts'].keys():
                raise ValueError('Scalar/fact evidence key collision')
            for kind, field in (('scalar', 'scalars'), ('fact', 'facts')):
                for key, value in snapshot[field].items():
                    reference = {**binding, 'key': key}
                    try:
                        identifier = _reference_id(reference)
                    except (UnicodeError, ValueError) as exc:
                        raise ValueError('Evidence reference is not finite UTF-8 JSON') from exc
                    if identifier in self._entries:
                        raise ValueError('Evidence ID hash collision')
                    self._entries[identifier] = {
                        'reference': reference, 'kind': kind, 'value': copy.deepcopy(value)}

    def entries(self):
        """Return the model-facing inventory, without full binding repetition."""
        result = []
        for identifier, entry in sorted(self._entries.items()):
            reference = entry['reference']
            result.append({'evidence_id': identifier,
                **{key: reference[key] for key in ('candidate_id', 'task_id', 'scope', 'key')},
                'kind': entry['kind'], 'value': copy.deepcopy(entry['value'])})
        return result

    def export_manifest(self):
        """Return a host-only exact ID mapping suitable for an immutable audit."""
        return {'version': VERSION, 'session_id': self._session_id,
                'entries': copy.deepcopy(dict(sorted(self._entries.items())))}

    def expand_claim(self, claim):
        """Resolve a closed compact claim without interpreting or correcting it."""
        if (not checks._closed(claim, _CLAIM_KEYS)
                or not _identifier(claim['evidence_id'])
                or type(claim['op']) is not str):
            return _invalid('claim_schema_invalid')
        op, value = claim['op'], claim['value']
        scalar_shape = op in checks._SCALAR_OPS and checks._number(value)
        fact_shape = op in checks._FACT_OPS and checks._atom(value)
        if not (scalar_shape or fact_shape):
            return _invalid('claim_schema_invalid')
        entry = self._entries.get(claim['evidence_id'])
        if entry is None:
            return {'status': 'unavailable', 'reason': 'reference_not_found'}
        if (entry['kind'] == 'scalar' and not scalar_shape
                or entry['kind'] == 'fact' and not fact_shape):
            return _invalid('claim_schema_invalid')
        return {'status': 'resolved', 'value': {'kind': entry['kind'],
                'reference': copy.deepcopy(entry['reference']),
                'op': op, 'value': copy.deepcopy(value)}}

    def expand_prediction(self, prediction):
        """Resolve a closed absolute-delta prediction; registration stays separate."""
        if (not checks._closed(prediction, _PREDICTION_KEYS)
                or not _identifier(prediction['evidence_id'])
                or type(prediction['direction']) is not str
                or prediction['direction'] not in {'increase', 'decrease'}
                or not checks._number(prediction['min_delta']) or prediction['min_delta'] < 0):
            return _invalid('prediction_schema_invalid')
        entry = self._entries.get(prediction['evidence_id'])
        if entry is None:
            return {'status': 'unavailable', 'reason': 'reference_not_found'}
        # A fact-only reference is passed through exactly. The original scalar
        # registration checker then reports key_missing, as before this adapter.
        return {'status': 'resolved', 'value': {
            'reference': copy.deepcopy(entry['reference']),
            'direction': prediction['direction'], 'min_delta': prediction['min_delta']}}

    def check_claim(self, claim):
        expanded = self.expand_claim(claim)
        if expanded['status'] != 'resolved':
            return expanded
        return checks.check_claim(expanded['value'], self._snapshots)

    def register_prediction(self, prediction):
        expanded = self.expand_prediction(prediction)
        if expanded['status'] != 'resolved':
            return expanded
        return checks.register_prediction(expanded['value'], self._snapshots)
