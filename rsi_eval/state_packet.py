"""Deterministic, bounded replacement for the complete model-visible history.

This module performs no model call, candidate execution or file access. The
caller persists full records before packing them. Only the selected incumbent
has source in this packet; rejected candidates remain identifiable by digest.
Byte counts use exactly the canonical JSON encoding used by PilotBudget.
"""
import copy
import hashlib
import json
import math
import re


MAX_SOURCE_BYTES = 16384
MAX_PACKET_BYTES = 65536
_HASH = re.compile(r'[0-9a-f]{64}')
_FEEDBACK_FIELDS = ('task_id', 'status', 'error_kind', 'exception_type',
                    'candidate_hash', 'run_id', 'candidate_line',
                    'first_invalid_action', 'plan_length', 'metrics')
_DIAGNOSTIC_FIELDS = ('version', 'task_id', 'candidate_sha256', 'scope',
                      'plan_replay', 'residuals')


def _canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False,
                          sort_keys=True, separators=(',', ':'))
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError('State packet requires finite JSON values') from exc


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def payload_bytes(payload):
    """Count the same UTF-8 JSON bytes as the pre-transport budget reservation."""
    return len(_canonical(payload).encode('utf-8'))


def _text(value, label, *, max_chars=2000, max_bytes=None, empty=True):
    if type(value) is not str or len(value) > max_chars or (not empty and not value.strip()):
        raise ValueError(label + ': invalid or oversized text')
    try:
        size = len(value.encode('utf-8'))
    except UnicodeError as exc:
        raise ValueError(label + ': invalid UTF-8 text') from exc
    if max_bytes is not None and size > max_bytes:
        raise ValueError(label + ': UTF-8 byte limit exceeded')
    return value


def _json_tree(value, label, *, max_bytes, max_string=8192, depth=0):
    """Validate bounded visible data without lossy truncation or coercion."""
    def visit(item, level):
        if level > 12:
            raise ValueError(label + ': nesting limit exceeded')
        if item is None or type(item) is bool:
            return
        if type(item) is int:
            if abs(item) > 10 ** 100:
                raise ValueError(label + ': integer limit exceeded')
            return
        if type(item) is float:
            if not math.isfinite(item):
                raise ValueError(label + ': nonfinite number')
            return
        if type(item) is str:
            _text(item, label, max_chars=max_string)
            return
        if type(item) is list:
            if len(item) > 256:
                raise ValueError(label + ': list limit exceeded')
            for child in item:
                visit(child, level + 1)
            return
        if type(item) is dict:
            if len(item) > 128:
                raise ValueError(label + ': object limit exceeded')
            for key, child in item.items():
                _text(key, label + ' key', max_chars=128, empty=False)
                visit(child, level + 1)
            return
        raise ValueError(label + ': not a JSON value')

    visit(value, depth)
    if payload_bytes(value) > max_bytes:
        raise ValueError(label + ': serialized byte limit exceeded')
    return copy.deepcopy(value)


def _list(value, label, maximum, *, minimum=0):
    if type(value) is not list or not minimum <= len(value) <= maximum:
        raise ValueError(label + ': list length outside contract')
    return value


def _metrics(value):
    if type(value) is not dict or any(type(number) not in (int, float) for number in value.values()):
        raise ValueError('metrics: expected numeric metric object')
    return _json_tree(value, 'metrics', max_bytes=2048)


def _feedback(value):
    if type(value) is not dict:
        raise ValueError('feedback: expected object')
    result = {key: value[key] for key in _FEEDBACK_FIELDS if key in value}
    if 'metrics' in result:
        result['metrics'] = _metrics(result['metrics'])
    if 'diagnostics' in value:
        diagnostic = value['diagnostics']
        if type(diagnostic) is not dict:
            raise ValueError('diagnostics: expected object')
        compact = {key: diagnostic[key] for key in _DIAGNOSTIC_FIELDS if key in diagnostic}
        if 'evidence_ids' in diagnostic:
            identifiers = _list(diagnostic['evidence_ids'], 'diagnostic evidence IDs', 8)
            compact['evidence_ids'] = [identifier for identifier in identifiers
                if _text(identifier, 'diagnostic evidence ID', max_chars=256).rsplit(':', 1)[-1]
                in ('plan_replay', 'residuals')]
        result['diagnostics'] = compact
    return _json_tree(result, 'latest feedback', max_bytes=16384)


def _selection(record):
    selection = record.get('selection', {})
    if type(selection) is not dict:
        raise ValueError('selection: expected object')
    if ('incumbent_id' in selection and 'incumbent_candidate_id' in selection
            and selection['incumbent_id'] != selection['incumbent_candidate_id']):
        raise ValueError('selection: incumbent IDs disagree')
    accepted = selection.get('accepted', False)
    if type(accepted) is not bool:
        raise ValueError('selection: accepted must be boolean')
    return selection


def _hash(value):
    if type(value) is not str or not _HASH.fullmatch(value):
        raise ValueError('source_sha256: expected lowercase SHA-256 digest')
    return value


def build_state_packet(*, session_id: str, task_text: str, public_examples: list,
                       records: list, evidence: list, audits: list,
                       checks_visible: bool, max_source_bytes=MAX_SOURCE_BYTES,
                       max_candidates=3) -> dict:
    """Build one finite snapshot, failing closed if a visible bound is exceeded.

    Evidence is already scoped by the controller to latest + incumbent. Audits
    are a separate channel: when hidden they are neither serialized, hashed,
    counted nor inspected, so changing a hidden checker result cannot change
    the packet. Full trace data contributes only to the archived-record digest.
    """
    if type(checks_visible) is not bool:
        raise ValueError('checks_visible must be boolean')
    if type(max_candidates) is not int or not 1 <= max_candidates <= 3:
        raise ValueError('max_candidates outside bounded candidate contract')
    if type(max_source_bytes) is not int or not 1 <= max_source_bytes <= MAX_SOURCE_BYTES:
        raise ValueError('max_source_bytes outside bounded source contract')
    _text(session_id, 'session_id', max_chars=256, empty=False)
    _text(task_text, 'task_text', max_chars=32768, max_bytes=32768, empty=False)
    _list(records, 'records', max_candidates + 1, minimum=1)
    _list(public_examples, 'public_examples', 2)
    _list(evidence, 'evidence', 6)

    by_id = {}
    history = []
    for record in records:
        if type(record) is not dict:
            raise ValueError('records: expected objects')
        identifier = _text(record.get('candidate_id'), 'candidate_id', max_chars=128, empty=False)
        if identifier in by_id:
            raise ValueError('records: duplicate candidate ID')
        parent = record.get('parent_id')
        if parent is not None:
            _text(parent, 'parent_id', max_chars=128, empty=False)
            if parent not in by_id:
                raise ValueError('records: parent must identify a previous candidate')
        source_hash = _hash(record.get('source_sha256'))
        if 'source' in record:
            source = _text(record['source'], 'record source', max_chars=65536, empty=False)
            if hashlib.sha256(source.encode('utf-8')).hexdigest() != source_hash:
                raise ValueError('record source hash mismatch')
        selected = _selection(record)
        history.append({'candidate_id': identifier, 'source_sha256': source_hash,
                        'parent_id': parent, 'score': _metrics(record.get('metrics', {})),
                        'accepted': selected.get('accepted', len(history) == 0)})
        by_id[identifier] = record

    latest = records[-1]
    selection = _selection(latest)
    incumbent_id = selection.get('incumbent_candidate_id', selection.get('incumbent_id'))
    if incumbent_id is None:
        incumbent_id = records[0]['candidate_id']
    if incumbent_id not in by_id:
        raise ValueError('selection: unknown incumbent ID')
    selected_record = by_id[incumbent_id]
    source = selection.get('incumbent_source', selected_record.get('source'))
    if source is None:
        source = _selection(selected_record).get('incumbent_source')
    _text(source, 'incumbent source', max_chars=max_source_bytes,
          max_bytes=max_source_bytes, empty=False)
    if hashlib.sha256(source.encode('utf-8')).hexdigest() != selected_record['source_sha256']:
        raise ValueError('incumbent source hash mismatch')
    n_params = selected_record.get('n_params')
    if type(n_params) is not int or not 0 <= n_params <= 16:
        raise ValueError('incumbent n_params outside candidate contract')

    latest_compact = {key: latest[key] for key in
        ('candidate_id', 'source_sha256', 'parent_id', 'status', 'origin', 'n_params') if key in latest}
    latest_compact.update(metrics=_metrics(latest.get('metrics', {})),
        rationale=_text(latest.get('rationale', ''), 'latest rationale'),
        results=[_feedback(value) for value in _list(latest.get('results', []), 'latest results', 10)],
        accepted=selection.get('accepted', len(records) == 1))
    remaining = latest.get('generated_candidates_remaining', max_candidates + 1 - len(records))
    if type(remaining) is not int or remaining != max_candidates + 1 - len(records):
        raise ValueError('generated candidate budget disagrees with record count')

    packet = {'version': 'compact-state-v0.1', 'session_id': session_id,
        'task_text': task_text,
        'public_examples': _json_tree(public_examples, 'public examples', max_bytes=32768),
        'incumbent': {'candidate_id': incumbent_id, 'source_sha256': selected_record['source_sha256'],
                      'n_params': n_params, 'source': source},
        'latest_candidate': _json_tree(latest_compact, 'latest candidate', max_bytes=32768),
        'history': history, 'generated_candidates_remaining': remaining,
        'selection_instruction': _text(selection.get('instruction',
            'Revise the selected incumbent next; retain rejected candidate feedback as evidence.'),
            'selection instruction'),
        'evidence': _json_tree(evidence, 'evidence', max_bytes=32768),
        'metadata': {'omitted_trace': True,
                     'persisted_files': ['candidates.json', 'diagnostics.json'],
                     'records_sha256': _digest(records), 'evidence_sha256': _digest(evidence)}}
    if checks_visible:
        _list(audits, 'audits', 3)
        packet['audits'] = _json_tree(audits, 'audits', max_bytes=24576)
        packet['metadata']['audits_sha256'] = _digest(audits)
    if payload_bytes(packet) > MAX_PACKET_BYTES:
        raise ValueError('state packet: serialized byte limit exceeded')
    return packet


def replace_messages(messages, packet) -> list:
    """Keep fixed system/developer messages and replace every other event."""
    if type(messages) is not list or any(type(message) is not dict for message in messages):
        raise ValueError('messages: expected list of objects')
    if type(packet) is not dict:
        raise ValueError('packet: expected object')
    retained = [copy.deepcopy(message) for message in messages
                if message.get('role') in ('system', 'developer')]
    return retained + [{'role': 'user', 'content': _canonical(packet)}]


def wire_payload(model, messages, tools, tool_choice, max_output_tokens) -> dict:
    """Construct the complete budgeted request, including tools and output cap."""
    _text(model, 'model', max_chars=256, empty=False)
    if type(max_output_tokens) is not int or max_output_tokens <= 0:
        raise ValueError('max_output_tokens must be a positive integer')
    payload = {'model': model, 'messages': messages, 'tools': tools,
               'tool_choice': tool_choice, 'max_output_tokens': max_output_tokens}
    _canonical(payload)
    return copy.deepcopy(payload)
