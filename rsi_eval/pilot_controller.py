"""Fixed-task, fixed-strategy development controller for one bounded pilot.

No LLM or SDK imports. All generated source goes through the existing sandbox.
The selection metrics here are development metrics, never held-out results.
"""
import hashlib
import json
import math
from pathlib import Path
import re

from . import planning
from .executor import evaluate_candidate


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def _project_file(root, relative, prefix):
    path = (root / relative).resolve()
    if not path.is_relative_to(root / prefix) or not path.is_file():
        raise ValueError('Invalid trusted pilot asset')
    return path


def _feedback(raw, task_id):
    result = {'task_id': task_id, 'status': raw.get('status', 'infrastructure_error')}
    allowed = {'success', 'task_failure', 'invalid_output', 'invalid_request', 'candidate_error',
               'candidate_process_error', 'timeout', 'resource_limit', 'output_limit', 'infrastructure_error'}
    if result['status'] not in allowed:
        result['status'] = 'infrastructure_error'
    for key in ('error_kind', 'exception_type', 'candidate_hash', 'run_id'):
        value = raw.get(key)
        if isinstance(value, str) and re.fullmatch(r'[a-zA-Z0-9_:-]{1,96}', value):
            result[key] = value
    for key in ('candidate_line', 'first_invalid_action', 'plan_length'):
        value = raw.get(key)
        if type(value) is int and 0 <= value <= 100000:
            result[key] = value
    metrics = raw.get('metrics', {})
    if isinstance(metrics, dict):
        result['metrics'] = {key: value for key, value in metrics.items()
                             if key in {'mse', 'nmse'} and type(value) is float
                             and math.isfinite(value) and value >= 0}
        # Host scores may be exact small integers in tests or future scorers.
        result['metrics'].update({key: float(value) for key, value in metrics.items()
                                  if key in {'mse', 'nmse'} and type(value) is int and 0 <= value < 10**300})
        if not result['metrics']:
            result.pop('metrics')
    return result


class PilotController:
    def __init__(self, root, session_config, output_dir, max_candidates=3):
        self.root = Path(root).resolve()
        self.config = dict(session_config)
        self.family = self.config['family']
        if self.family not in ('planning', 'symbolic') or self.config['session_id'] != self.family:
            raise ValueError('Unsupported pilot session')
        self.task_ids = list(self.config['task_ids'])
        self.prompt_ids = list(self.config['prompt_task_ids'])
        allowed = [f'spannerlearning/seed0/problem{i}' for i in range(10)]
        if self.family == 'planning':
            if self.task_ids != allowed or self.prompt_ids != allowed[:2]:
                raise ValueError('Pilot planning batch must be the fixed authorized 2/8 tasks')
        elif self.task_ids != ['oscillator1'] or self.prompt_ids:
            raise ValueError('Pilot symbolic task must be oscillator1 training only')
        self.strategy_version = self.config['strategy_version']
        if self.strategy_version != 'fixed-revision-v0.1':
            raise ValueError('Pilot strategy is fixed')
        if self.config['max_generated_candidates'] != 3 or max_candidates != 3:
            raise ValueError('Pilot candidate budget is fixed at three')
        self.max_candidates = 3
        self.initial_n_params = self.config['initial_n_params']
        if self.initial_n_params != (0 if self.family == 'planning' else 1):
            raise ValueError('Unexpected initial parameter count')
        initial_bytes = _project_file(self.root, self.config['initial_candidate'], 'fixtures').read_bytes()
        if hashlib.sha256(initial_bytes).hexdigest() != self.config['initial_candidate_sha256']:
            raise ValueError('Initial candidate integrity mismatch')
        self.initial_source = initial_bytes.decode('utf-8')
        self.prompt_template = _project_file(self.root, self.config['prompt_file'], 'prompts').read_text(encoding='utf-8')
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if (self.output_dir / 'candidates.json').exists():
            raise ValueError('A pilot controller cannot overwrite an existing session')
        (self.output_dir / 'candidates').mkdir(exist_ok=True)
        self.records = []
        self.rejections = []
        self.halted = False

    def baseline(self):
        if self.records:
            return self.records[0]
        return self._evaluate(self.initial_source, self.initial_n_params, 'Fixed weak starting candidate.', initial=True)

    def submit(self, source, n_params=3, rationale=''):
        if not self.records:
            raise RuntimeError('Evaluate the baseline before starting the Agent')
        if self.halted:
            return {'status': 'infrastructure_error', 'error_kind': 'pilot_halted'}
        if len(self.records) - 1 >= self.max_candidates:
            return self._reject('budget_exhausted', 'candidate_budget_exhausted')
        if (not isinstance(source, str) or not source.strip() or len(source.encode('utf-8')) > 65536
                or type(n_params) is not int or not 0 <= n_params <= 16
                or not isinstance(rationale, str) or len(rationale) > 2000):
            return self._reject('invalid_request', 'candidate_contract')
        return self._evaluate(source, n_params, rationale)

    def _reject(self, status, kind):
        entry = {'status': status, 'error_kind': kind}
        self.rejections.append(entry)
        _write(self.output_dir / 'rejections.json', self.rejections)
        return entry

    def _evaluate(self, source, n_params, rationale, initial=False):
        index = len(self.records)
        candidate_id = f'{self.family}-{index:03d}'
        incumbent = self.summary()['best'] if self.records else None
        parent = incumbent['candidate_id'] if incumbent else None
        record = {'candidate_id': candidate_id, 'parent_id': parent,
                  'source_sha256': hashlib.sha256(source.encode('utf-8')).hexdigest(),
                  'origin': 'hand_authored_initial' if initial else 'model_proposed',
                  'n_params': n_params, 'rationale': rationale,
                  'strategy_version': self.strategy_version, 'results': [],
                  'feedback_role': 'development_only', 'metric_scope': 'Development feedback only; no held-out evaluation.'}
        (self.output_dir / 'candidates' / f'{candidate_id}.py').write_text(source, encoding='utf-8')
        # Persist each candidate before execution, including a partial record if interrupted.
        self.records.append(record)
        _write(self.output_dir / 'candidates.json', self.records)
        for task_id in self.task_ids:
            try:
                raw = evaluate_candidate(self.family, task_id, source, root=self.root,
                    n_params=n_params, candidate_id=candidate_id, parent_id=parent,
                    strategy_version=self.strategy_version)
            except Exception as exc:
                raw = {'status': 'infrastructure_error', 'error_kind': 'controller_exception',
                       'exception_type': type(exc).__name__}
            feedback = _feedback(raw, task_id)
            record['results'].append(feedback)
            _write(self.output_dir / 'candidates.json', self.records)
            if feedback['status'] in ('infrastructure_error', 'invalid_request'):
                self.halted = True
                break
        record['status'] = 'infrastructure_error' if self.halted else 'evaluated'
        if self.family == 'planning':
            prompt_good = sum(r['status'] == 'success' for r in record['results'] if r['task_id'] in self.prompt_ids)
            dev_good = sum(r['status'] == 'success' for r in record['results'] if r['task_id'] not in self.prompt_ids)
            record['metrics'] = dict(prompt_successes=prompt_good, prompt_total=2,
                development_successes=dev_good, development_total=8,
                total_successes=prompt_good+dev_good, total_tasks=10)
        else:
            record['metrics'] = record['results'][0].get('metrics', {})
            record['metric_split'] = 'train'
            record['metric_scope'] = 'Training fit only; not generalization or equation recovery.'
        record['generated_candidates_used'] = len(self.records) - 1
        record['generated_candidates_remaining'] = max(0, self.max_candidates - len(self.records) + 1)
        selected = self.summary()['best']
        record['selection'] = {
            'accepted': selected is record,
            'incumbent_id': selected['candidate_id'] if selected else None,
            'incumbent_source': ((self.output_dir / 'candidates' / (selected['candidate_id'] + '.py')).read_text(encoding='utf-8')
                                 if selected else None),
            'instruction': 'Revise the selected incumbent next; retain rejected candidate feedback as evidence.'}
        _write(self.output_dir / 'candidates.json', self.records)
        _write(self.output_dir / 'summary.json', self.summary())
        return record

    def _rank(self, record):
        if record.get('status') != 'evaluated':
            return (float('-inf'),)
        metrics = record['metrics']
        if self.family == 'planning':
            return (metrics['development_successes'], metrics['prompt_successes'])
        value = metrics.get('nmse')
        if (record['results'][0]['status'] != 'success' or type(value) not in (int, float)
                or not math.isfinite(value)):
            return (float('-inf'),)
        return (-value,)

    def summary(self):
        ranked = [r for r in self.records if self._rank(r)[0] != float('-inf')]
        best = max(ranked, key=self._rank) if ranked else None
        return {'family': self.family, 'session_id': self.family, 'strategy_version': self.strategy_version,
                'strategy_updated': False, 'generated_candidates': max(0, len(self.records)-1),
                'tool_rejections': len(self.rejections), 'halted': self.halted,
                'executions': sum(len(r['results']) for r in self.records),
                'baseline': self.records[0] if self.records else None,
                'first': self.records[1] if len(self.records)>1 else None,
                'last': self.records[-1] if len(self.records)>1 else None, 'best': best,
                'selection_rule': 'development_successes_then_prompt_then_earlier' if self.family == 'planning' else 'lowest_finite_train_nmse_then_earlier',
                'sealed_tasks_executed': 0, 'scope': 'Fixed-strategy development pilot; not an RSI effectiveness experiment.'}

    def task_prompt(self):
        if not self.records:
            raise RuntimeError('Baseline feedback is required')
        examples = [planning.prepare_task(task_id, self.root) for task_id in self.prompt_ids]
        context = {'initial_source': self.initial_source, 'initial_feedback': self.records[0],
                   'prompt_examples': examples, 'max_generated_candidates': self.max_candidates}
        return (self.prompt_template + '\n\nTrusted starting context:\n' +
                json.dumps(context, ensure_ascii=False, indent=2, allow_nan=False) +
                '\nSubmit each complete candidate with submit_candidate(source, n_params, rationale). '
                'After feedback, revise the selected incumbent identified in the selection field. '
                'You may finish early if the planning batch is fully solved. '
                'Use at most three candidate submissions and finish when the budget is exhausted.')
