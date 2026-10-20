"""A/B/C development comparison with equal diagnostic execution for all arms."""
import hashlib
import json
import math

from .executor import evaluate_candidate
from .pilot_controller import PilotController, _feedback, _write
from .planning_trace import sanitize_trace


_KEYS = set('''version task_id candidate_sha256 scope trace plan_replay residuals
status reason error error_kind executed_actions plan_length first_failed_action index action
missing_preconditions missing_preconditions_truncated unsatisfied_goals unsatisfied_goals_truncated
events_seen event_limit truncated interrupted provenance none_return_caveat interpretation_limits
lines line hits functions name first_line call_events return_events none_return_events
exception_events return_types none list tuple dict set bool int float str other
container_length_min container_length_max residual_definition n bias rmse standardized_bias
standardized_bias_reason standardized_bias_definition binning_method inputs boundaries bins
lower upper upper_inclusive count mean_residual'''.split())


def _bounded_tree(value, depth=0):
    if depth > 10:
        return False
    if value is None or type(value) is bool:
        return True
    if type(value) is int:
        return abs(value) <= 10**100
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is str:
        return len(value) <= 512
    if type(value) is list:
        return len(value) <= 128 and all(_bounded_tree(item, depth+1) for item in value)
    if type(value) is dict:
        return (len(value) <= 64 and set(value) <= _KEYS
                and all(_bounded_tree(item, depth+1) for item in value.values()))
    return False


class DiagnosticController(PilotController):
    def __init__(self, root, session_config, output_dir, *, arm, policy_text):
        if arm not in ('A', 'B', 'C') or not isinstance(policy_text, str) or not policy_text.strip():
            raise ValueError('Invalid diagnostic comparison condition')
        super().__init__(root, session_config, output_dir)
        self.arm = arm
        self.strategy_version = 'diagnostic-' + arm + '-v0.1'
        self.hidden_observations = {}
        # Keep the task interface/domain intact, replace only its revision policy.
        if '## Fixed revision procedure' not in self.prompt_template:
            raise ValueError('Missing task/policy boundary in base prompt')
        self.prompt_template = self.prompt_template.split('## Fixed revision procedure')[0]
        self.prompt_template = self.prompt_template.replace(
            'Semantic failure feedback currently says that a precondition or final goal is unsatisfied; '
            'it does not provide a complete state trace or exact missing precondition.',
            'Feedback may include bounded diagnostic observations according to the assigned condition.')
        self.prompt_template += '\n## Revision policy\n\n' + policy_text
        if arm in ('B', 'C'):
            self.prompt_template += (
                '\n\nDiagnostic observations use stable evidence IDs within each candidate/task. '
                'Plan replay is host-derived; Python tracing is candidate-process debugging evidence '
                'and can be incomplete or interfered with. Missing line hits do not prove nonexecution. '
                'Residuals are prediction minus target; marginal bins describe association, not causes. '
                'Do not treat any of these as automatic proof of a causal explanation.')

    def _evaluate_task(self, task_id, source, n_params, candidate_id, parent):
        return evaluate_candidate(self.family, task_id, source, root=self.root, n_params=n_params,
            candidate_id=candidate_id, parent_id=parent, strategy_version=self.strategy_version,
            diagnostics=True)

    def _visible_feedback(self, raw, task_id):
        feedback = _feedback(raw, task_id)
        diagnostic = raw.get('diagnostics')
        if diagnostic is None:
            return feedback
        candidate = self.records[-1]
        expected_scope = 'public_prompt' if self.family == 'planning' else 'train'
        expected_sections = {'trace', 'plan_replay'} if self.family == 'planning' else {'residuals'}
        header = {'version', 'task_id', 'candidate_sha256', 'scope'}
        valid = (type(diagnostic) is dict and set(diagnostic) <= header | expected_sections
                 and header <= set(diagnostic) and _bounded_tree(diagnostic)
                 and diagnostic['version'] == 'diagnostics-v0.1'
                 and diagnostic['task_id'] == task_id and diagnostic['scope'] == expected_scope
                 and diagnostic['candidate_sha256'] == candidate['source_sha256']
                 and (self.family != 'planning' or task_id in self.prompt_ids))
        if valid and 'trace' in diagnostic:
            trace = diagnostic['trace']
            valid = (sanitize_trace(trace) is not None or trace in (
                     {'status': 'unavailable', 'reason': 'missing_or_invalid_candidate_trace'},
                     {'status': 'unavailable', 'reason': 'candidate_trace_exceeds_feedback_budget'}))
        if not valid:
            return {'task_id': task_id, 'status': 'infrastructure_error', 'error_kind': 'diagnostic_contract'}
        encoded = json.dumps(diagnostic, ensure_ascii=False, allow_nan=False, sort_keys=True)
        if len(encoded.encode('utf-8')) > 32768:
            return {'task_id': task_id, 'status': 'infrastructure_error', 'error_kind': 'diagnostic_size'}
        safe = json.loads(encoded)
        safe['evidence_ids'] = [task_id + ':' + key for key in sorted(expected_sections & set(safe))]
        self.hidden_observations.setdefault(candidate['candidate_id'], []).append(safe)
        _write(self.output_dir/'diagnostics.json', self.hidden_observations)
        if self.arm != 'A':
            feedback['diagnostics'] = safe
        return feedback

    def initial_observation_digest(self):
        if not self.records:
            raise RuntimeError('Baseline must be evaluated first')
        observations = self.hidden_observations.get(self.records[0]['candidate_id'], [])
        expected = 2 if self.family == 'planning' else 1
        if len(observations) != expected:
            raise ValueError('Initial diagnostic packet incomplete')
        content = json.dumps(observations, sort_keys=True, ensure_ascii=False, allow_nan=False)
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def summary(self):
        result = super().summary()
        result.update(arm=getattr(self, 'arm', None),
                      diagnostics_computed=True,
                      diagnostics_visible=getattr(self, 'arm', 'A') != 'A',
                      scope='Exploratory fixed-prompt comparison on previously used development tasks.')
        return result
