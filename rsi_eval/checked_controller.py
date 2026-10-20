"""Trusted evidence adapters and a feedback-only, fixed-policy comparison."""
import copy
import json
import math

from . import planning
from .diagnostic_controller import DiagnosticController
from .evidence_checks import check_claim, register_prediction, check_prediction
from .pilot_controller import _write
from .planning_diagnostics import is_public_prompt
from .state_packet import build_state_packet, payload_bytes


def public_contract_facts(task_id, root):
    # Authorize before loading even a development TaskView.
    if not is_public_prompt(task_id, root):
        raise PermissionError('Only public prompt contracts are available')
    domain, task, _ = planning._load_task(task_id, root)
    facts = {'init': [list(a) for a in sorted(task['init'])],
             'goal': [list(a) for a in sorted(task['goal'])]}
    for name, operator in sorted(domain['operators'].items()):
        positions = {parameter: '$'+str(i) for i, parameter in enumerate(operator['parameters'])}
        facts['action.'+name+'.parameters'] = [[positions[p], kind]
                                              for p, kind in operator['parameters'].items()]
        for section in ('preconditions', 'effects'):
            for negative, label in ((False, 'positive'), (True, 'negative')):
                facts['action.'+name+'.'+section+'.'+label] = [
                    [atom[0]] + [positions[arg] for arg in atom[1:]]
                    for neg, atom in operator[section] if neg == negative]
    return facts


def _finite(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


class CheckedController(DiagnosticController):
    def __init__(self, root, session_config, output_dir, *, condition, session_id, policy_text):
        if condition not in ('hidden', 'checked') or not isinstance(session_id, str):
            raise ValueError('Invalid checked-feedback condition')
        self.condition = condition
        self.evidence_session = session_id
        self.audits = []
        super().__init__(root, session_config, output_dir, arm='B', policy_text=policy_text)
        self.strategy_version = 'checked-feedback-v0.2'
        self.public_facts = {task: public_contract_facts(task, self.root) for task in self.prompt_ids}
        self.public_examples = [planning.prepare_task(task, self.root) for task in self.prompt_ids]

    def evidence_for(self, record):
        def snapshot(task, scope, scalars, facts=None):
            return {'binding': {'session_id': self.evidence_session,
                    'candidate_id': record['candidate_id'], 'candidate_sha256': record['source_sha256'],
                    'task_id': task, 'version': 'evidence-v0.1', 'scope': scope},
                    'scalars': {key: _finite(value) for key, value in scalars.items()},
                    'facts': copy.deepcopy(facts or {})}
        if self.family == 'planning':
            complete = (record.get('status') == 'evaluated'
                and [r['task_id'] for r in record.get('results', [])] == self.task_ids)
            aggregate = {key: value if complete else None for key, value in record.get('metrics', {}).items()}
            values = [snapshot('planning_batch', 'development_summary', aggregate)]
            for observation in self.hidden_observations.get(record['candidate_id'], []):
                task = observation['task_id']
                if task not in self.public_facts:
                    raise PermissionError('Nonpublic diagnostic evidence')
                replay = observation.get('plan_replay', {})
                scalars = {key: replay.get(key) for key in ('executed_actions', 'plan_length')}
                values.append(snapshot(task, 'public_prompt', scalars, self.public_facts[task]))
            return values
        if record.get('status') != 'evaluated':
            return [snapshot('oscillator1', 'train', {})]
        metrics = dict(record.get('metrics', {}))
        observations = self.hidden_observations.get(record['candidate_id'], [])
        residuals = observations[0].get('residuals', {}) if observations else {}
        if residuals.get('status') == 'ok':
            metrics.update({key: residuals.get(key) for key in ('bias', 'rmse', 'standardized_bias')})
            bias, mse = _finite(metrics.get('bias')), _finite(metrics.get('mse'))
            metrics['abs_bias'] = abs(bias) if bias is not None else None
            ratio = bias*bias/mse if bias is not None and mse is not None and mse > 0 else None
            metrics['bias_squared_over_mse'] = _finite(ratio)
            for feature in residuals.get('inputs', []):
                for i, bucket in enumerate(feature['bins']):
                    for key in ('mean_residual', 'rmse'):
                        metrics['bin.'+feature['name']+'.'+str(i)+'.'+key] = (
                            bucket.get(key) if bucket.get('count', 0) > 0 else None)
        return [snapshot('oscillator1', 'train', metrics)]

    def current_evidence(self):
        if not self.records:
            return []
        selected = self.summary()['best']
        wanted = {self.records[-1]['candidate_id']}
        if selected:
            wanted.add(selected['candidate_id'])
        return [snapshot for record in self.records if record['candidate_id'] in wanted
                for snapshot in self.evidence_for(record)]

    def _persist_evidence(self):
        _write(self.output_dir/'evidence.json', {r['candidate_id']: self.evidence_for(r) for r in self.records})

    def baseline(self):
        result = super().baseline()
        self._persist_evidence()
        return result

    def submit(self, source, n_params=3, rationale='', *, claims=None, prediction=None):
        if self.halted or len(self.records)-1 >= self.max_candidates:
            return super().submit(source, n_params, rationale)
        if not self.records:
            raise RuntimeError('Baseline required')
        if (type(source) is not str or not source.strip() or len(source.encode('utf-8')) > 16384
                or type(n_params) is not int or not 0 <= n_params <= 16
                or type(rationale) is not str or len(rationale) > 2000
                or type(claims) is not list or not 1 <= len(claims) <= 2
                or type(prediction) is not dict):
            return self._reject('invalid_request', 'checked_submission_contract')
        try:
            encoded = json.dumps({'claims': claims, 'prediction': prediction}, allow_nan=False)
        except (ValueError, TypeError):
            return self._reject('invalid_request', 'checked_submission_contract')
        if len(encoded.encode('utf-8')) > 2048:
            return self._reject('invalid_request', 'checked_submission_contract')
        evidence = self.current_evidence()
        audit = {'candidate_id': self.family+'-'+str(len(self.records)).zfill(3),
                 'claims': copy.deepcopy(claims), 'prediction': copy.deepcopy(prediction),
                 'claim_results': [check_claim(claim, evidence) for claim in claims],
                 'registration': register_prediction(prediction, evidence)}
        self.audits.append(audit)
        # Pre-execution registration is persisted before any candidate task runs.
        _write(self.output_dir/'audits.json', self.audits)
        child = super().submit(source, n_params, rationale)
        if child.get('candidate_id') != audit['candidate_id']:
            raise RuntimeError('Candidate registration/dispatch mismatch')
        audit['prediction_result'] = check_prediction(audit['registration'], self.evidence_for(child))
        _write(self.output_dir/'audits.json', self.audits)
        self._persist_evidence()
        # SDK logs receive a short acknowledgement; transport uses the complete
        # deterministic state packet and never the growing SDK event history.
        feedback = {'candidate_id': child['candidate_id'], 'status': child['status'],
                    'metrics': child.get('metrics', {}),
                    'selection': {key: value for key, value in child['selection'].items()
                                  if key != 'incumbent_source'}}
        if self.condition == 'checked':
            feedback['audit'] = copy.deepcopy(audit)
        return feedback

    def state_packet(self):
        # Declarations already travel in their own common channel. Checks use
        # claim indices to avoid repeating those references/atoms a second time.
        def result_view(result):
            fields = ('status', 'reason', 'op', 'actual', 'before', 'after', 'tolerance')
            view = {key: result[key] for key in fields if key in result}
            if type(result.get('expected')) in (int, float):
                view['expected'] = result['expected']
            return view
        compact_audits = [{'candidate_id': a['candidate_id'],
            'claim_results': [dict(claim_index=i, **result_view(result))
                              for i, result in enumerate(a['claim_results'])],
            'prediction_result': result_view(a['prediction_result'])}
            for a in self.audits if 'prediction_result' in a]
        packet = build_state_packet(session_id=self.evidence_session, task_text=self.prompt_template,
            public_examples=self.public_examples, records=self.records, evidence=self.current_evidence(),
            audits=compact_audits, checks_visible=self.condition == 'checked')
        packet['generated_candidates_remaining'] = max(0, self.max_candidates-len(self.records)+1)
        packet['selection_instruction'] = 'Revise incumbent; retain latest rejected feedback. Finish at zero remaining.'
        # Both conditions retain the model's own submissions, without revealing
        # hidden checker outcomes or their hashes.
        packet['declared_hypotheses'] = [{key: a[key] for key in ('candidate_id', 'claims', 'prediction')}
                                         for a in self.audits]
        if self.rejections:
            packet['latest_submission_rejection'] = copy.deepcopy(self.rejections[-1])
            packet['submission_rejection_count'] = len(self.rejections)
        if payload_bytes(packet) > 65536:
            raise ValueError('Complete state packet exceeds 65536 bytes')
        return packet

    def task_prompt(self):
        return json.dumps(self.state_packet(), ensure_ascii=False, allow_nan=False, sort_keys=True,
                          separators=(',', ':'))

    def summary(self):
        result = super().summary()
        result.pop('arm', None)
        result.update(condition=self.condition, checks_visible=self.condition == 'checked',
                      check_gates_execution=False, check_changes_selection=False,
                      scope='Exploratory typed-check feedback visibility; fixed policy; reused development states.')
        return result
