"""Freeze an unexecuted draft, then compare matched reviews of its commitments."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from .decision_core import DecisionController
from .executor import evaluate_candidate
from .edit_consistency import inspect_edit, assess_claim
from .two_stage_core import _case, _copy_json, _identifier, _sha, _write, canonical

ROOT = Path(__file__).resolve().parents[1]
VERSION = STRATEGY = 'edit-commitment-v0.1'
EDIT_CLAIMS = ('keep_bytes', 'keep_ast', 'apply_format_patch', 'remove_selected_term', 'general_edit')
DEPLOYMENT_CLAIMS = ('raw_validation', 'probe_repair_deployed', 'unspecified')
FIELDS = ('source', 'n_params', 'edit_claim', 'deployment_claim', 'rationale', 'auxiliary')


def validate_submission(source, n_params, edit_claim, deployment_claim, rationale='', auxiliary=None):
    if (type(source) is not str or not source.strip() or len(source.encode('utf-8')) > 16384
            or type(n_params) is not int or not 0 <= n_params <= 16
            or type(edit_claim) is not str or edit_claim not in EDIT_CLAIMS
            or type(deployment_claim) is not str or deployment_claim not in DEPLOYMENT_CLAIMS
            or type(rationale) is not str or len(rationale) > 4000):
        raise ValueError('Invalid structured commitment submission')
    auxiliary = {} if auxiliary is None else auxiliary
    if type(auxiliary) is not dict:
        raise ValueError('Auxiliary must be a finite JSON object')
    return _copy_json(dict(source=source, n_params=n_params, edit_claim=edit_claim,
        deployment_claim=deployment_claim, rationale=rationale, auxiliary=auxiliary))


def _business(value):
    return validate_submission(**{k: value[k] for k in FIELDS})


def _metadata(case, value):
    for key, expected in [('case_id',case['id']), ('base_source_sha256',case['source_sha256']),
                          ('source_sha256',_sha(value['source']))]:
        if key in value and value[key] != expected:
            raise ValueError('Submission metadata binding mismatch: '+key)


def _deployment(case, kind, root):
    if case['family'] != 'planning' or kind == 'unspecified':
        return dict(kind=kind, status='unknown', reason='not_applicable_or_unspecified')
    # A manually audited fact tied to the old runtime; do not infer arbitrary host behavior.
    from scripts.analyze_edit_consistency import CONFIG, CONFIG_SHA256, deployment_verdict
    raw = (Path(root)/CONFIG).read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIG_SHA256:
        raise ValueError('Deployment fact source changed')
    pins = json.loads(raw)['deployment_contract']['runtime_files_sha256']
    known = deployment_verdict(root, 'final_host_normalization', pins)
    return dict(kind=kind, status='supported' if kind == 'raw_validation' else 'contradicted',
        reason=known['reason'], scope=known['scope'])


def check_submission(case, submission, root=ROOT):
    value = _business(submission)
    _metadata(case,submission)
    inspection = inspect_edit(case, value['source'], value['n_params'])
    return dict(version=VERSION, source_sha256=_sha(value['source']),
        case_id=case['id'],base_source_sha256=case['source_sha256'],n_params=value['n_params'],
        commitment_sha256=hashlib.sha256(canonical(value)).hexdigest(),
        edit_claim=dict(kind=value['edit_claim'], **assess_claim(inspection, value['edit_claim'])),
        deployment_claim=_deployment(case, value['deployment_claim'], root),
        scope='Named static relation only; not a proof of rationale, utility or arbitrary semantics.')


def review_change(case, draft, candidate, root=ROOT):
    before = _business(draft); after = _business(candidate)
    initial = check_submission(case, before, root)
    actual = check_submission(case, after, root)
    under_original = assess_claim(inspect_edit(case, after['source'], after['n_params']), before['edit_claim'])
    source_changed = after['source'] != before['source']
    parameters_changed = after['n_params'] != before['n_params']
    claim_changed = after['edit_claim'] != before['edit_claim']
    deployment_changed = after['deployment_claim'] != before['deployment_claim']
    return dict(initial_claim=initial['edit_claim'], under_original_claim=under_original,
        under_final_claim=actual['edit_claim'], source_changed=source_changed,
        parameters_changed=parameters_changed, edit_claim_changed=claim_changed,
        deployment_claim_changed=deployment_changed,
        original_commitment_repaired=(initial['edit_claim']['status']=='contradicted'
            and under_original['status']=='supported' and (source_changed or parameters_changed)),
        declaration_only_change=(claim_changed or deployment_changed) and not (source_changed or parameters_changed),
        final_general_edit=after['edit_claim']=='general_edit',
        returned_to_base=(after['source']==case['source'] and after['n_params']==case['n_params']),
        initial_deployment=initial['deployment_claim'], final_deployment=actual['deployment_claim'],
        draft_task_performance='not_measured')


def _packet(case, stage, draft=None, feedback=None):
    # Reuse the immutable public task/diagnostic projection and objective text.
    view = SimpleNamespace(case=case, feedback=case['archive_feedback'])
    packet = DecisionController.task_packet(view)
    packet.update(version=VERSION, stage=stage, draft=copy.deepcopy(draft),
        checker_feedback=copy.deepcopy(feedback),
        commitment_contract={
            'edit_claim': list(EDIT_CLAIMS), 'deployment_claim': list(DEPLOYMENT_CLAIMS),
            'reference': 'All edit claims compare your submitted source to the original base, not to the draft.',
            'planning_format': 'apply_format_patch means only the registered _fmt inner-edge whitespace patch; whole outside AST and parameter metadata unchanged.',
            'symbolic_removal': 'remove_selected_term means only the bound independent term and matching retained formula; general mathematical rewrites may be unknown.',
            'keep': 'keep_bytes is exact UTF-8 and parameter metadata; keep_ast ignores locations and ordinary comments/whitespace, preserves other AST structure. Type-ignore attachment semantics are not certified.',
            'general_edit': 'Legal broader edits are unknown under this checker and are still evaluated in the final stage.',
            'deployment': 'raw_validation means the final executor checks the raw plan against its original syntax gate before later token normalization; it does not claim the plan passes that gate. probe_repair_deployed claims the diagnostic copy repair is automatically applied before that gate. unspecified makes no such claim.',
            'revision': 'You may change the draft, its declarations, both, or neither. We separately record whether the original claim is fulfilled; relabeling alone is not code repair. A commitment is not an obligation to perform an unsuitable edit.',
            'timing': 'The draft and declarations are frozen together before external checking. The draft is never executed; no draft task performance is known.',
            'evaluation': 'Only final submissions are executed. Do not equate static support with success or an unknown verdict with an error.'})
    packet['auxiliary_contract'].pop('decision', None)
    return _copy_json(packet)


def common_request(payload):
    result = copy.deepcopy(payload)
    if type(result) is not dict or type(result.get('messages')) is not list:
        raise ValueError('Expected complete request envelope')
    users=[m for m in result['messages'] if m.get('role')=='user']
    if len(users)!=1 or type(users[0].get('content')) is not str:
        raise ValueError('Exactly one review packet required')
    from .two_stage_audit import _json
    packet=_json(users[0]['content'])
    if type(packet) is not dict or 'checker_feedback' not in packet:
        raise ValueError('Missing sole permitted feedback channel')
    packet.pop('checker_feedback');users[0]['content']=canonical(packet).decode()
    return _copy_json(result,maximum=1024*1024)


class DraftController:
    def __init__(self, case, outputdir):
        self.case = _case(case); self.output_dir = Path(outputdir)
        if any(p.is_symlink() for p in (self.output_dir, *self.output_dir.parents)):
            raise ValueError('Symlinked draft output')
        self.output_dir.mkdir(parents=True, exist_ok=True)
        with (self.output_dir/'controller-binding.json').open('x', encoding='utf-8') as stream:
            json.dump(dict(version=VERSION, stage='draft', case_id=self.case['id'],
                           source_sha256=self.case['source_sha256']), stream)
        self.draft = None; self.attempts = []; self.halted = False
        self.infrastructure_error_type = None

    def task_packet(self): return _packet(self.case, 'draft')
    def task_prompt(self): return canonical(self.task_packet()).decode()
    def state_packet(self): return self.task_packet()

    def submit(self, session_id=None, source='', n_params=0, rationale='', auxiliary=None,
               edit_claim=None, deployment_claim=None):
        if self.halted: return {'status':'infrastructure_error', 'error_kind':'controller_halted'}
        if self.attempts: return {'status':'budget_exhausted', 'error_kind':'one_draft_attempt'}
        attempt = dict(session_id=session_id, status='invalid_request'); self.attempts.append(attempt)
        try:
            _identifier(session_id, optional=True)
            business = validate_submission(source,n_params,edit_claim,deployment_claim,rationale,auxiliary)
        except (ValueError,TypeError,UnicodeError,OverflowError,RecursionError):
            attempt['error_kind']='commitment_contract';_write(self.output_dir/'attempts.json',self.attempts)
            return copy.deepcopy(attempt)
        self.draft = dict(business, version=VERSION, status='accepted', source_file='draft.py',
            source_sha256=_sha(source), base_source_sha256=self.case['source_sha256'], case_id=self.case['id'])
        (self.output_dir/'draft.py').write_bytes(source.encode())
        _write(self.output_dir/'draft.json',self.draft)
        attempt.update(status='accepted',source_sha256=_sha(source));_write(self.output_dir/'attempts.json',self.attempts)
        _write(self.output_dir/'controller-summary.json',self.summary())
        return dict(status='accepted',source_sha256=_sha(source),candidate_executions=0)

    def summary(self):
        return dict(version=VERSION,draft=copy.deepcopy(self.draft),attempts=len(self.attempts),
                    halted=self.halted,infrastructure_error_type=self.infrastructure_error_type,
                    candidate_executions=0,model_calls_owned=0,sealed_tasks_executed=0)


class ReviewController(DecisionController):
    def __init__(self, case, draft, checker_feedback, root, outputdir, evaluator=None):
        _metadata(case,draft)
        self.draft = _business(draft)
        expected = check_submission(case,self.draft,root)
        if checker_feedback is not None and canonical(checker_feedback)!=canonical(expected):
            raise ValueError('Feedback does not bind the frozen draft and declaration')
        self.checker_feedback = copy.deepcopy(checker_feedback)
        original = evaluator or evaluate_candidate
        def evaluate(*args,**kwargs):
            kwargs['strategy_version']=STRATEGY
            return original(*args,**kwargs)
        super().__init__(case,None,root,outputdir,evaluator=evaluate)
        _write(self.output_dir/'controller-binding.json',dict(version=VERSION,stage='review',
            case_id=self.case['id'],base_source_sha256=self.case['source_sha256'],
            draft_sha256=_sha(self.draft['source']),draft_commitment_sha256=hashlib.sha256(canonical(self.draft)).hexdigest()))

    def task_packet(self): return _packet(self.case,'review',self.draft,self.checker_feedback)

    def summary(self):
        result=super().summary()
        result['underlying_controller_version']=result['version']
        result.update(version=VERSION,stage='review')
        return result

    def submit(self,session_id=None,source='',n_params=0,rationale='',auxiliary=None,
               edit_claim=None,deployment_claim=None):
        if self.attempts or self.halted:
            return super().submit(session_id,source,n_params,rationale,auxiliary)
        try:
            value=validate_submission(source,n_params,edit_claim,deployment_claim,rationale,auxiliary)
        except (ValueError,TypeError,UnicodeError,OverflowError,RecursionError):
            # Preserve the single-attempt rule even for malformed business data.
            return super().submit(session_id,'',n_params,rationale,auxiliary)
        # Write commitments and checks before any evaluator dispatch.
        checked=check_submission(self.case,value,self.root)
        change=review_change(self.case,self.draft,value,self.root)
        _write(self.output_dir/'final-commitment.json',dict(value,source_sha256=_sha(source),
            commitment_check=checked,review_change=change))
        result=super().submit(session_id,source,n_params,rationale,auxiliary)
        if self.candidate is not None:
            self.candidate.update(edit_claim=edit_claim,deployment_claim=deployment_claim,
                                  commitment_check=checked,review_change=change)
            _write(self.output_dir/'candidate.json',self.candidate)
            _write(self.output_dir/'controller-summary.json',self.summary())
        return result
