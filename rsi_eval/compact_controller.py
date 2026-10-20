"""One new revision of a verified archived state, with exact compact evidence.

The baseline is copied from an immutable, hash-verified repair-state loader;
it is not evaluated again and does not count as a new execution. Both arms
receive the same candidate, source, diagnostics, historical declarations and
current evidence IDs. Only explicit check-result fields vary by condition.
The checker never gates execution or changes the fixed selection rule.
"""
import copy
import hashlib
import json

from .checked_controller import CheckedController
from .diagnostic_controller import DiagnosticController
from .evidence_checks import check_prediction
from .evidence_ids import EvidenceRegistry
from .pilot_controller import _write
from .state_packet import build_state_packet, payload_bytes


def _digest(value):
    text = json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _result_view(result):
    fields = ('status', 'reason', 'op', 'actual', 'before', 'after', 'tolerance',
              'direction', 'min_delta', 'expected')
    return {key: copy.deepcopy(result[key]) for key in fields if key in result}


def _invalid_constant(value):
    raise ValueError('Nonfinite JSON constant')


class CompactController(CheckedController):
    def __init__(self, root, session_config, output_dir, *, condition, session_id,
                 policy_text, repair_state):
        # Original pilot config validation remains unchanged. This separate
        # protocol narrows its runtime budget after the original initializer.
        super().__init__(root, session_config, output_dir, condition=condition,
                         session_id=session_id, policy_text=policy_text)
        self.max_candidates = 1
        self.strategy_version = 'paired-compact-feedback-v0.1'
        self.repair_state = copy.deepcopy(repair_state)
        seed = self.repair_state
        required = {'state_id', 'family', 'source', 'n_params', 'record', 'diagnostics',
                    'historical_common', 'historical_checks', 'provenance'}
        if type(seed) is not dict or not required <= set(seed) or seed['family'] != self.family:
            raise ValueError('Invalid archived repair state')
        source, record = seed['source'], seed['record']
        if (type(source) is not str or not source.strip() or len(source.encode('utf-8')) > 16384
                or type(record) is not dict or record.get('status') != 'evaluated'
                or hashlib.sha256(source.encode('utf-8')).hexdigest() != record.get('source_sha256')
                or type(seed['n_params']) is not int or not 0 <= seed['n_params'] <= 16
                or seed['n_params'] != record.get('n_params')
                or [r.get('task_id') for r in record.get('results', [])] != self.task_ids):
            raise ValueError('Archived source, parameter or task binding mismatch')
        diagnostics = seed['diagnostics']
        expected_tasks = self.prompt_ids if self.family == 'planning' else self.task_ids
        if (type(diagnostics) is not list
                or [d.get('task_id') for d in diagnostics] != expected_tasks
                or any(d.get('candidate_sha256') != record['source_sha256'] for d in diagnostics)):
            raise ValueError('Archived diagnostics do not match the repair state')
        self.initial_source = source
        self.initial_n_params = seed['n_params']

    def _registry(self):
        return EvidenceRegistry(self.current_evidence(), session_id=self.evidence_session)

    def _persist_registry(self):
        manifest = self._registry().export_manifest()
        filename = 'evidence-registry-' + str(len(self.records)-1).zfill(3) + '.json'
        _write(self.output_dir/filename, manifest)
        _write(self.output_dir/'evidence-registry.json', manifest)
        return {'file': filename, 'sha256': _digest(manifest)}

    def baseline(self):
        if self.records:
            return self.records[0]
        seed = self.repair_state
        record = copy.deepcopy(seed['record'])
        candidate_id = self.family + '-000'
        record.update(candidate_id=candidate_id, parent_id=None,
            origin='archived_model_proposed_initial', strategy_version=self.strategy_version,
            generated_candidates_used=0, generated_candidates_remaining=1)
        # The selected repair state may have been rejected in its old rollout.
        # It is the explicit starting artifact in this new paired experiment.
        record['selection'] = {'accepted': True, 'incumbent_id': candidate_id,
            'incumbent_source': self.initial_source,
            'instruction': 'Revise this explicit archived starting candidate once.'}
        (self.output_dir/'candidates'/(candidate_id+'.py')).write_bytes(
            self.initial_source.encode('utf-8'))
        self.records.append(record)
        self.hidden_observations[candidate_id] = copy.deepcopy(seed['diagnostics'])
        _write(self.output_dir/'candidates.json', self.records)
        _write(self.output_dir/'diagnostics.json', self.hidden_observations)
        _write(self.output_dir/'repair-state-provenance.json', seed['provenance'])
        self._persist_evidence()
        self._persist_registry()
        _write(self.output_dir/'summary.json', self.summary())
        return record

    def submit(self, source, n_params=3, rationale='', *, claim_id, claim_op,
               claim_value_json, prediction_id, prediction_direction, prediction_min_delta):
        if not self.records:
            raise RuntimeError('Archived baseline required')
        if self.halted or len(self.records)-1 >= self.max_candidates:
            return DiagnosticController.submit(self, source, n_params, rationale)
        if (type(source) is not str or not source.strip() or len(source.encode('utf-8')) > 16384
                or type(n_params) is not int or not 0 <= n_params <= 16
                or type(rationale) is not str or len(rationale) > 2000):
            return self._reject('invalid_request', 'compact_submission_contract')
        declaration = {'claim_id': claim_id, 'claim_op': claim_op,
            'claim_value_json': claim_value_json, 'prediction_id': prediction_id,
            'prediction_direction': prediction_direction, 'prediction_min_delta': prediction_min_delta}
        try:
            bounded = (all(type(declaration[key]) is str and len(declaration[key]) <= limit
                           for key, limit in [('claim_id', 128), ('claim_op', 32),
                                              ('prediction_id', 128), ('prediction_direction', 32)])
                and type(claim_value_json) is str and len(claim_value_json.encode('utf-8')) <= 2048
                and payload_bytes(declaration) <= 4096)
        except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
            bounded = False
        if not bounded:
            return self._reject('invalid_request', 'compact_submission_contract')
        registry = self._registry()
        registry_reference = self._persist_registry()
        try:
            value = json.loads(claim_value_json, parse_constant=_invalid_constant)
            # JSON escape decoding can create lone surrogates or 1e400 can
            # overflow to infinity. Such values cannot enter a UTF-8 audit.
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
        except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
            value = None
        claim = {'evidence_id': claim_id, 'op': claim_op, 'value': value}
        prediction = {'evidence_id': prediction_id, 'direction': prediction_direction,
                      'min_delta': prediction_min_delta}
        audit = {'candidate_id': self.family+'-'+str(len(self.records)).zfill(3),
            'compact_declaration': copy.deepcopy(declaration), 'registry': registry_reference,
            'claim_expansion': registry.expand_claim(claim),
            'prediction_expansion': registry.expand_prediction(prediction),
            'claim_results': [registry.check_claim(claim)],
            'registration': registry.register_prediction(prediction)}
        self.audits.append(audit)
        # The exact declaration, lookup result, parent value and registry digest
        # are durable before any task evaluation of the child can begin.
        _write(self.output_dir/'audits.json', self.audits)
        child = DiagnosticController.submit(self, source, n_params, rationale)
        if child.get('candidate_id') != audit['candidate_id']:
            raise RuntimeError('Compact candidate registration/dispatch mismatch')
        audit['prediction_result'] = check_prediction(audit['registration'], self.evidence_for(child))
        _write(self.output_dir/'audits.json', self.audits)
        self._persist_evidence()
        self._persist_registry()
        _write(self.output_dir/'summary.json', self.summary())
        feedback = {'candidate_id': child['candidate_id'], 'status': child['status'],
            'metrics': child.get('metrics', {}),
            'selection': {key: value for key, value in child['selection'].items()
                          if key != 'incumbent_source'}}
        if self.condition == 'checked':
            feedback['audit'] = self._audit_view(audit)
        return feedback

    @staticmethod
    def _audit_view(audit):
        return {'candidate_id': audit['candidate_id'],
            'claim_results': [_result_view(result) for result in audit['claim_results']],
            'prediction_result': _result_view(audit['prediction_result'])}

    def state_packet(self):
        packet = build_state_packet(session_id=self.evidence_session, task_text=self.prompt_template,
            public_examples=self.public_examples, records=self.records, evidence=self.current_evidence(),
            audits=[], checks_visible=False, max_candidates=1)
        inventory = self._registry().entries()
        packet['version'] = 'paired-compact-state-v0.1'
        packet['evidence'] = inventory
        packet['metadata']['evidence_sha256'] = _digest(inventory)
        packet['checks_visible'] = self.condition == 'checked'
        packet['selection_instruction'] = 'Revise the explicit starting artifact once; no second candidate.'
        packet['frozen_history_common'] = copy.deepcopy(self.repair_state['historical_common'])
        packet['declared_hypotheses'] = [{'candidate_id': audit['candidate_id'],
            **copy.deepcopy(audit['compact_declaration'])} for audit in self.audits]
        if self.condition == 'checked':
            packet['frozen_history_checks'] = copy.deepcopy(self.repair_state['historical_checks'])
            packet['audits'] = [self._audit_view(audit) for audit in self.audits
                                if 'prediction_result' in audit]
        # No check-result hashes, counts or condition labels enter other fields.
        if self.rejections:
            packet['latest_submission_rejection'] = copy.deepcopy(self.rejections[-1])
            packet['submission_rejection_count'] = len(self.rejections)
        if payload_bytes(packet) > 65536:
            raise ValueError('Complete compact state packet exceeds 65536 bytes')
        return packet

    def summary(self):
        result = super().summary()
        result['archived_task_records'] = len(self.records[0]['results']) if self.records else 0
        result['executions'] = sum(len(record['results']) for record in self.records[1:])
        result['baseline_reexecuted'] = False
        result['max_generated_candidates'] = 1
        result['scope'] = ('One revision of an archived development state; paired check visibility; '
                           'fixed policy and weights; no held-out scoring or strategy update.')
        return result
