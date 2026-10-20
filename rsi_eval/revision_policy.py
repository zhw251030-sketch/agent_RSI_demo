"""One-shot selection of a finite, host-rendered revision strategy.

No SDK, candidate executor, credentials or model call lives here. Model text is
archived only: the transferable policy contains exactly four distinct rule IDs
in order, and the renderer can emit only the predefined generic instructions.
The caller must verify known usage before freeze_policy; this module validates
the accepted submission and exact persisted bytes, not a provider ledger.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re


VERSION = 'revision-policy-v0.1'
RULES = {
    'R01': 'Check the input and output types, required format, and parameter order before diagnosing a search failure.',
    'R02': 'Prioritize the earliest failure actually observed during execution; do not equate proposed plan length with executed actions.',
    'R03': 'Preserve the explicit task rules and constraints; do not rewrite the environment definition to repair an artifact.',
    'R04': 'Use the exact metric, units, sign, candidate identity, and data scope; do not substitute one statistic for another.',
    'R05': 'Connect a diagnostic observation to the source location to change and the failure expected to disappear; verify that the submitted source includes that change.',
    'R06': 'Treat marginal associations as hypotheses, consider alternative explanations, and do not declare an associated structure necessary.',
    'R07': 'Compare previous forecasts with observed changes and choose an absolute improvement threshold proportionate to the evidence.',
    'R08': 'Preserve correct behavior while making a complete valid repair, and avoid unrelated complexity.',
}
S0 = {'version': VERSION, 'rule_ids': ['R03', 'R04', 'R06', 'R08']}
_POLICY_KEYS = frozenset({'version', 'rule_ids'})
_CASE_KEYS = frozenset({'case_id', 'family', 'parent_metrics', 'child_metrics', 'rationale',
    'observations_before', 'observations_after', 'claim_results', 'prediction_result'})
_CHECK_KEYS = frozenset({'status', 'reason', 'op', 'actual', 'before', 'after', 'tolerance',
                       'direction', 'min_delta', 'expected', 'metric_key'})
_PLANNING_METRICS = frozenset({'prompt_successes', 'prompt_total', 'development_successes',
                             'development_total', 'total_successes', 'total_tasks'})
_PLAN_KEYS = frozenset({'error_kind', 'executed_actions', 'first_failed_action', 'action', 'index',
    'missing_preconditions', 'missing_preconditions_truncated', 'plan_length', 'status',
    'unsatisfied_goals', 'unsatisfied_goals_truncated'})
_RESIDUAL_KEYS = frozenset({'bias', 'binning_method', 'inputs', 'n', 'residual_definition',
    'rmse', 'scope', 'standardized_bias', 'standardized_bias_definition',
    'standardized_bias_reason', 'status', 'name', 'boundaries', 'bins', 'count',
    'lower', 'mean_residual', 'upper', 'upper_inclusive'})
_SUBMISSION_KEYS = frozenset({'version', 'status', 'parent_policy_sha256', 'policy_sha256',
    'update_bundle_sha256', 'rule_support', 'rationale', 'no_op'})
_FREEZE_KEYS = frozenset({'version', 'request_id', 'parent_policy_sha256', 'policy_sha256',
    'update_bundle_sha256', 'policy_file_sha256', 'submission_sha256',
    'submission_file_sha256', 'no_op', 'freeze_sha256'})
_OUTPUT_FILES = ('policy-S1.json', 'policy-submission.json', 'freeze.json', 'policy-attempt.json')
_REQUEST = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')


def _canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False,
                          sort_keys=True, separators=(',', ':')).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ValueError('Expected finite UTF-8 JSON') from exc


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _digest(value):
    return _sha(_canonical(value))


def _closed(value, keys):
    return type(value) is dict and set(value) == keys


def _text(value, limit=2000):
    return type(value) is str and len(value) <= limit


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except (ValueError, OverflowError):
        return False


def _bounded_tree(value, allowed_keys, depth=0):
    if depth > 10:
        return False
    if value is None or type(value) is bool:
        return True
    if type(value) in (int, float):
        return _number(value)
    if type(value) is str:
        return len(value) <= 512
    if type(value) is list:
        return len(value) <= 128 and all(_bounded_tree(x, allowed_keys, depth+1) for x in value)
    if type(value) is dict:
        return (len(value) <= 32 and set(value) <= allowed_keys
                and all(_bounded_tree(x, allowed_keys, depth+1) for x in value.values()))
    return False


def _validate_bundle(bundle):
    if (not _closed(bundle, {'version', 'cases'})
            or bundle['version'] != 'policy-update-cases-v0.1'
            or type(bundle['cases']) is not list or len(bundle['cases']) != 2):
        raise ValueError('Update bundle must contain only its two authorized cases')
    if len(_canonical(bundle)) > 32768:
        raise ValueError('Update bundle exceeds its input bound')
    for case, identifier, family in zip(bundle['cases'], ('U-P', 'U-S'), ('planning', 'symbolic')):
        if (not _closed(case, _CASE_KEYS) or case['case_id'] != identifier
                or case['family'] != family or not _text(case['rationale'])):
            raise ValueError('Unexpected update case fields or identity')
        metric_keys = _PLANNING_METRICS if family == 'planning' else frozenset({'mse', 'nmse'})
        for name in ('parent_metrics', 'child_metrics'):
            metrics = case[name]
            if not _closed(metrics, metric_keys) or any(not _number(x) for x in metrics.values()):
                raise ValueError('Unexpected update metrics')
        for name in ('observations_before', 'observations_after'):
            observations = case[name]
            if type(observations) is not list or len(observations) > (2 if family == 'planning' else 1):
                raise ValueError('Unexpected update observation count')
            section = 'plan_replay' if family == 'planning' else 'residuals'
            scope = 'public_prompt' if family == 'planning' else 'train'
            tasks = {'spannerlearning/seed0/problem0', 'spannerlearning/seed0/problem1'} if family == 'planning' else {'oscillator1'}
            for observation in observations:
                if (not _closed(observation, {'task_id', 'scope', section})
                        or observation['task_id'] not in tasks or observation['scope'] != scope
                        or not _bounded_tree(observation[section],
                                             _PLAN_KEYS if family == 'planning' else _RESIDUAL_KEYS)):
                    raise ValueError('Unexpected update diagnostic projection')
        claims = case['claim_results']
        if type(claims) is not list or not 1 <= len(claims) <= 2:
            raise ValueError('Unexpected update claim count')
        for result in claims + [case['prediction_result']]:
            if (type(result) is not dict or not {'status', 'reason'} <= set(result)
                    or not set(result) <= _CHECK_KEYS or not _bounded_tree(result, _CHECK_KEYS)):
                raise ValueError('Unexpected update check projection')
    return copy.deepcopy(bundle)


def catalog():
    return [{'rule_id': identifier, 'instruction': instruction}
            for identifier, instruction in RULES.items()]


def validate_policy(policy):
    if (not _closed(policy, _POLICY_KEYS) or policy['version'] != VERSION
            or type(policy['rule_ids']) is not list or len(policy['rule_ids']) != 4
            or any(type(rule) is not str or rule not in RULES for rule in policy['rule_ids'])
            or len(set(policy['rule_ids'])) != 4):
        raise ValueError('Policy requires exactly four distinct known rules in order')
    return copy.deepcopy(policy)


def render_policy(policy):
    value = validate_policy(policy)
    return {**value, 'instructions': [RULES[rule] for rule in value['rule_ids']]}


def _artifact_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8') + b'\n'


def _write_exclusive(path, value):
    encoded = _artifact_bytes(value)
    try:
        with path.open('xb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except (FileExistsError, OSError) as exc:
        raise ValueError('Policy artifact cannot be overwritten or persisted') from exc


def _read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError('Missing or invalid policy artifact')
    raw = path.read_bytes()
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON field in policy artifact')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Nonfinite policy artifact constant')
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
        _canonical(value)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError('Invalid policy artifact JSON') from exc
    return value, raw


def _accepted(output_dir, bundle, parent):
    directory = Path(output_dir)
    policy, policy_raw = _read(directory/'policy-S1.json')
    submission, submission_raw = _read(directory/'policy-submission.json')
    policy = validate_policy(policy)
    if (not _closed(submission, _SUBMISSION_KEYS)
            or submission['version'] != 'policy-submission-v0.1' or submission['status'] != 'accepted'
            or submission['parent_policy_sha256'] != _digest(parent)
            or submission['policy_sha256'] != _digest(policy)
            or submission['update_bundle_sha256'] != _digest(bundle)
            or not _text(submission['rationale']) or type(submission['no_op']) is not bool
            or submission['no_op'] != (policy == parent)):
        raise ValueError('Accepted policy submission context mismatch')
    supports = submission['rule_support']
    if (type(supports) is not list or len(supports) != 4
            or any(not _closed(item, {'rule_id', 'support'})
                   or item['rule_id'] != identifier or item['support'] not in ('U-P', 'U-S', 'both')
                   for item, identifier in zip(supports, policy['rule_ids']))):
        raise ValueError('Accepted rule supports are invalid')
    return policy, submission, policy_raw, submission_raw


class PolicyUpdateController:
    """Persist a single model selection; invalid first attempts cannot be repaired."""
    def __init__(self, update_bundle, parent_policy, output_dir):
        self._bundle = _validate_bundle(update_bundle)
        self._parent = validate_policy(parent_policy)
        self.output_dir = Path(output_dir)
        if self.output_dir.is_symlink():
            raise ValueError('Policy directory must not be a symlink')
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if any((self.output_dir/name).exists() or (self.output_dir/name).is_symlink() for name in _OUTPUT_FILES):
            raise ValueError('Policy attempt already exists; no overwrite or resume')
        self._policy = None
        self._attempted = False
        self._status = 'ready'
        self.halted = False
        prompt = Path(__file__).resolve().parents[1]/'prompts/policy-transfer/update.md'
        self._task_text = prompt.read_text(encoding='utf-8')

    @property
    def policy(self):
        return copy.deepcopy(self._policy)

    def state_packet(self):
        return {'version': 'policy-update-state-v0.1', 'task_text': self._task_text,
                'catalog': catalog(), 'parent_policy': render_policy(self._parent),
                'experience_cases': copy.deepcopy(self._bundle['cases'])}

    def task_prompt(self):
        return _canonical(self.state_packet()).decode('utf-8')

    def submit_policy(self, *, rule_1, rule_2, rule_3, rule_4,
                      support_1, support_2, support_3, support_4, rationale):
        if self._attempted:
            return {'status': 'invalid_request', 'error_kind': 'policy_update_already_attempted'}
        self._attempted = True
        try:
            _write_exclusive(self.output_dir/'policy-attempt.json', {
                'version': 'policy-attempt-v0.1', 'parent_policy_sha256': _digest(self._parent),
                'update_bundle_sha256': _digest(self._bundle)})
            policy = validate_policy({'version': VERSION, 'rule_ids': [rule_1, rule_2, rule_3, rule_4]})
            supports = [support_1, support_2, support_3, support_4]
            if (any(type(value) is not str or value not in ('U-P', 'U-S', 'both') for value in supports)
                    or not _text(rationale)):
                raise ValueError('Invalid support or rationale')
            _canonical(rationale)
            submission = {'version': 'policy-submission-v0.1', 'status': 'accepted',
                'parent_policy_sha256': _digest(self._parent), 'policy_sha256': _digest(policy),
                'update_bundle_sha256': _digest(self._bundle),
                'rule_support': [{'rule_id': rule, 'support': support}
                                 for rule, support in zip(policy['rule_ids'], supports)],
                'rationale': rationale, 'no_op': policy == self._parent}
            # The attempt marker prevents another controller from racing these
            # exclusive writes. A partial failure is retained and fails loading.
            _write_exclusive(self.output_dir/'policy-S1.json', policy)
            _write_exclusive(self.output_dir/'policy-submission.json', submission)
        except (ValueError, TypeError, UnicodeError, OSError):
            self.halted = True
            self._status = 'rejected'
            return {'status': 'invalid_request', 'error_kind': 'policy_submission_contract'}
        self._policy = policy
        self._status = 'accepted'
        return {'status': 'accepted', 'policy_sha256': _digest(policy), 'no_op': policy == self._parent}

    def summary(self):
        return {'status': self._status, 'halted': self.halted, 'attempted': self._attempted,
                'policy_changed': self._policy is not None and self._policy != self._parent,
                'no_op': self._policy == self._parent if self._policy is not None else None,
                'policy_sha256': _digest(self._policy) if self._policy is not None else None,
                'parent_policy_sha256': _digest(self._parent),
                'update_bundle_sha256': _digest(self._bundle),
                'candidate_executions': 0, 'scope': 'Selection and ordering of four predefined revision rules.'}


def freeze_policy(output_dir, update_bundle, parent_policy, request_id):
    """Freeze an accepted selection after the caller confirms known request usage.

    This independently reloads the two submission artifacts, checks context and
    records their exact byte hashes. It neither knows nor changes a cost ledger.
    An existing freeze is never overwritten, even if all values are identical.
    """
    if type(request_id) is not str or _REQUEST.fullmatch(request_id) is None:
        raise ValueError('Invalid policy update request identity')
    bundle, parent = _validate_bundle(update_bundle), validate_policy(parent_policy)
    policy, submission, policy_raw, submission_raw = _accepted(output_dir, bundle, parent)
    frozen = {'version': 'policy-freeze-v0.1', 'request_id': request_id,
        'parent_policy_sha256': _digest(parent), 'policy_sha256': _digest(policy),
        'update_bundle_sha256': _digest(bundle), 'policy_file_sha256': _sha(policy_raw),
        'submission_sha256': _digest(submission), 'submission_file_sha256': _sha(submission_raw),
        'no_op': policy == parent}
    # Self-check detects accidental edits, not a malicious writer capable of
    # replacing every record and recomputing hashes. The caller should retain
    # this file's external byte digest at the process boundary as well.
    frozen['freeze_sha256'] = _digest(frozen)
    _write_exclusive(Path(output_dir)/'freeze.json', frozen)
    return copy.deepcopy(frozen)


def load_frozen_policy(directory, expected_bundle, parent_policy):
    """Load only a context-bound, unchanged policy; never render free model text."""
    bundle, parent = _validate_bundle(expected_bundle), validate_policy(parent_policy)
    policy, submission, policy_raw, submission_raw = _accepted(directory, bundle, parent)
    frozen, freeze_raw = _read(Path(directory)/'freeze.json')
    if (not _closed(frozen, _FREEZE_KEYS) or frozen['version'] != 'policy-freeze-v0.1'
            or type(frozen['request_id']) is not str or _REQUEST.fullmatch(frozen['request_id']) is None
            or frozen['parent_policy_sha256'] != _digest(parent)
            or frozen['policy_sha256'] != _digest(policy)
            or frozen['update_bundle_sha256'] != _digest(bundle)
            or frozen['policy_file_sha256'] != _sha(policy_raw)
            or frozen['submission_sha256'] != _digest(submission)
            or frozen['submission_file_sha256'] != _sha(submission_raw)
            or type(frozen['no_op']) is not bool or frozen['no_op'] != (policy == parent)
            or frozen['freeze_sha256'] != _digest({key: value for key, value in frozen.items()
                                                   if key != 'freeze_sha256'})
            or freeze_raw != _artifact_bytes(frozen)):
        raise ValueError('Frozen policy integrity or context mismatch')
    return policy
