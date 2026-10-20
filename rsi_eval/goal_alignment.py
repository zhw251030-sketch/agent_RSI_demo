"""Pure, researcher-defined goal acceptance and paired strategy comparison.

No SDK, execution, file access or network activity occurs here. Checks concern
the supplied records, not their authenticity or prior registration time. The
caller must audit actual execution, snapshot freezes and complete provenance.
An accepted declaration is never substituted for measured task benefit.
"""
import hashlib
import json
import math
import re


VERSION = 'goal-alignment-v0.1'
EPSILON = 1e-5
TOLERANCE = 1e-10
_HASH = re.compile(r'[0-9a-f]{64}\Z')
_MEASURED_STATUSES = frozenset({'success', 'task_failure', 'invalid_output',
    'candidate_error', 'candidate_process_error', 'timeout', 'resource_limit', 'output_limit'})
_SCOPE_KEYS = ('task_id', 'metric_scope', 'data_sha256', 'evaluator_sha256')
_STATE_KEYS = frozenset({'id','family','base_source_sha256','base_n_params','task_ids',
    'development_ids','public_ids','metric_scope','feedback_sha256','model_config_sha256',
    'budget_sha256','evaluator_sha256','data_sha256','replicate_ids'})
_MEASUREMENT_KEYS = frozenset({'policy_sha256','allocation_sha256','context_sha256',
    'state_id','replicate_id','request_id','source_sha256','n_params','status','results','evaluation_sha256'})


def _canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                          separators=(',', ':')).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as error:
        raise ValueError('Expected finite JSON') from error


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _number(value):
    try:
        return type(value) in (int,float) and math.isfinite(value) and value >= 0
    except (ValueError,OverflowError):
        return False


def _params(value):
    return type(value) is int and value >= 0


def _hash(value):
    return type(value) is str and _HASH.fullmatch(value) is not None


def _ids(value, *, empty=False):
    if (type(value) is not list or (not empty and not value)
            or any(type(item) is not str or not item or len(item)>256 for item in value)
            or len(set(value)) != len(value)):
        raise ValueError('Identifiers must be a unique list of nonempty strings')
    return value


def _result(family, decision='unknown', reasons=(), metrics=None, details=None):
    return dict(version=VERSION, family=family, decision=decision,
        reason_codes=list(reasons), metrics=metrics or {}, details=details or {})


def _planning_map(rows, expected):
    if type(rows) is not list:
        return None,'missing_evaluations'
    result={}
    for row in rows:
        if type(row) is not dict or type(row.get('task_id')) is not str:
            return None,'invalid_evaluation_record'
        task=row['task_id']
        if task in result or task not in expected:
            return None,'task_allocation_mismatch'
        if type(row.get('status')) is not str or row['status'] not in _MEASURED_STATUSES:
            return None,'unmeasured_or_invalid_status'
        result[task]=row['status']=='success'
    if set(result)!=set(expected):
        return None,'missing_evaluations'
    return result,None


def assess_planning(parent_results, candidate_results, *, development_ids, public_ids):
    """Accept additional development success only if no old success is lost.

Raw records may contain other fields. Only task identity and measured status
affect this rule; claim wording cannot grant or remove measured success. Bad
allocation arguments raise ValueError; unusable observations yield unknown.
"""
    development_ids=_ids(development_ids)
    public_ids=_ids(public_ids,empty=True)
    if set(development_ids)&set(public_ids):
        raise ValueError('Public and development task allocations overlap')
    expected=public_ids+development_ids
    parent,parent_error=_planning_map(parent_results,expected)
    candidate,candidate_error=_planning_map(candidate_results,expected)
    if parent_error or candidate_error:
        return _result('planning', reasons=sorted(set(x for x in (parent_error,candidate_error) if x)),
            details={'parent_error':parent_error,'candidate_error':candidate_error})
    details={}
    for name,tasks in [('development',development_ids),('public',public_ids)]:
        details[name]=dict(parent_success_ids=[t for t in tasks if parent[t]],
            candidate_success_ids=[t for t in tasks if candidate[t]],
            gained_ids=[t for t in tasks if candidate[t] and not parent[t]],
            lost_ids=[t for t in tasks if parent[t] and not candidate[t]])
    dev,pub=details['development'],details['public']
    metrics=dict(development_delta=len(dev['gained_ids'])-len(dev['lost_ids']),
        public_delta=len(pub['gained_ids'])-len(pub['lost_ids']),
        parent_development_successes=len(dev['parent_success_ids']),
        candidate_development_successes=len(dev['candidate_success_ids']),
        parent_public_successes=len(pub['parent_success_ids']),
        candidate_public_successes=len(pub['candidate_success_ids']),
        development_total=len(development_ids),public_total=len(public_ids))
    if dev['lost_ids'] or pub['lost_ids']:
        return _result('planning','reject',['previous_success_lost'],metrics,details)
    if dev['gained_ids']:
        return _result('planning','promote',['development_success_added_without_regression'],metrics,details)
    return _result('planning','retain',['no_development_benefit'],metrics,details)


def assess_symbolic(parent, candidate):
    """Compare two directly measured formulas, separating accuracy/simplicity.

    Each input needs finite nonnegative nmse and a nonnegative integer n_params.
Optional task_id/metric_scope/data_sha256/evaluator_sha256 must be present on
both sides and equal if either provides them. Minimal numeric projections do
not authenticate scope: a caller using them must bind provenance separately.
"""
    if (type(parent) is not dict or type(candidate) is not dict
            or any(not _number(x.get('nmse')) or not _params(x.get('n_params')) for x in (parent,candidate))):
        return _result('symbolic', reasons=['missing_or_invalid_metrics'])
    for key in _SCOPE_KEYS:
        if (key in parent or key in candidate) and (key not in parent or key not in candidate or parent[key]!=candidate[key]):
            return _result('symbolic', reasons=['measurement_scope_mismatch'],details={'field':key})
    delta=candidate['nmse']-parent['nmse']
    if not math.isfinite(delta):
        return _result('symbolic',reasons=['nonfinite_metric_difference'])
    parameter_delta=candidate['n_params']-parent['n_params']
    metrics=dict(parent_nmse=parent['nmse'],candidate_nmse=candidate['nmse'],delta_nmse=delta,
        parent_n_params=parent['n_params'],candidate_n_params=candidate['n_params'],
        parameter_delta=parameter_delta,epsilon=EPSILON,tolerance=TOLERANCE,
        meaningful_improvement=None,acceptable_simplification=None)
    details=dict(complexity_proxy='independent_parameter_count_only',
        comparison='candidate_final_minus_parent_final')
    if abs(delta-EPSILON)<=TOLERANCE or abs(delta+EPSILON)<=TOLERANCE:
        return _result('symbolic','unknown',['threshold_boundary'],metrics,details)
    improved=delta < -EPSILON-TOLERANCE
    simplified=parameter_delta<0 and delta<EPSILON-TOLERANCE
    metrics.update(meaningful_improvement=improved,acceptable_simplification=simplified)
    if improved or simplified:
        reasons=(['meaningful_accuracy_gain'] if improved else [])+(['acceptable_simplification'] if simplified else [])
        return _result('symbolic','promote',reasons,metrics,details)
    if delta>EPSILON+TOLERANCE:
        return _result('symbolic','reject',['error_increase_exceeds_tolerance'],metrics,details)
    if parameter_delta>0:
        return _result('symbolic','reject',['more_parameters_without_meaningful_gain'],metrics,details)
    return _result('symbolic','retain',['no_meaningful_benefit'],metrics,details)


def symbolic_opportunity(original_nmse, removed_nmse, sham_nmse, original_params, removed_params):
    """Interpret a calibrated removal probe; never certify a final candidate.

The explicit proposition is removal loss > epsilon. A false proposition can
support a simplification trial; it does not assert final measured benefit.
Negative loss beyond numeric tolerance is inconsistent with this restricted
matched nested-fit calibration and remains unknown.
"""
    proposition=dict(quantity='removed_nmse - original_nmse',relation='>',
        threshold=EPSILON,tolerance=TOLERANCE,value=None,truth=None,
        negated_object='removal loss exceeds epsilon; not simplification itself')
    result=_result('symbolic_probe',reasons=['unvalidated_probe'],
        details={'final_candidate_benefit_measured':False,
                 'scope':'Matched local probe only; no physical necessity or generalization claim.'})
    result.update(proposition=proposition,opportunity='unknown')
    if not all(_number(x) for x in (original_nmse,removed_nmse,sham_nmse)):
        result['reason_codes']=['missing_or_invalid_probe_metrics'];return result
    if not _params(original_params) or not _params(removed_params) or removed_params>=original_params:
        result['reason_codes']=['invalid_simplification_parameter_counts'];return result
    delta=removed_nmse-original_nmse;sham_delta=sham_nmse-original_nmse
    if not math.isfinite(delta) or not math.isfinite(sham_delta):
        result['reason_codes']=['nonfinite_probe_difference'];return result
    result['metrics']=dict(original_nmse=original_nmse,removed_nmse=removed_nmse,
        sham_nmse=sham_nmse,loss=delta,sham_delta_nmse=sham_delta,
        original_n_params=original_params,removed_n_params=removed_params)
    proposition['value']=delta
    if abs(sham_delta)>TOLERANCE:
        result['reason_codes']=['sham_drift'];return result
    if delta < -TOLERANCE:
        result['reason_codes']=['nested_fit_inconsistent'];return result
    if abs(delta-EPSILON)<=TOLERANCE:
        result['reason_codes']=['threshold_boundary'];return result
    proposition['truth']=delta>EPSILON+TOLERANCE
    result['decision']='retain'  # A probe cannot by itself promote a final artifact.
    if proposition['truth']:
        result.update(opportunity='avoid_supported_harm',reason_codes=['removal_loss_exceeds_threshold'])
    else:
        result.update(opportunity='eligible_for_trial',reason_codes=['removal_loss_below_threshold'])
    return result


def _policy(snapshot):
    required={'content','renderer_sha256','sha256'}
    if (type(snapshot) is not dict or not required<=set(snapshot)
            or not set(snapshot)<=required|{'policy_id'} or type(snapshot['content']) is not dict
            or not snapshot['content'] or not _hash(snapshot['renderer_sha256']) or not _hash(snapshot['sha256'])
            or ('policy_id' in snapshot and (type(snapshot['policy_id']) is not str or not snapshot['policy_id']))):
        raise ValueError('Invalid strategy snapshot')
    body={key:snapshot[key] for key in ('content','renderer_sha256')}
    if snapshot['sha256']!=_digest(body):
        raise ValueError('Strategy content hash mismatch')
    return snapshot['sha256']


def _allocation(value):
    if (type(value) is not dict or set(value)!={'version','role','states','sha256'}
            or value['version']!='goal-selection-allocation-v0.1' or value['role']!='selection'
            or not _hash(value['sha256']) or value['sha256']!=_digest({k:v for k,v in value.items() if k!='sha256'})
            or type(value['states']) is not list or not value['states']):
        raise ValueError('Invalid frozen selection allocation')
    states={}
    for st in value['states']:
        if type(st) is not dict or set(st)!=_STATE_KEYS:
            raise ValueError('Unexpected selection state fields')
        _ids([st['id']]);_ids(st['task_ids']);_ids(st['replicate_ids'])
        _ids(st['development_ids'],empty=True);_ids(st['public_ids'],empty=True)
        if st['id'] in states or st['family'] not in ('planning','symbolic') or not _params(st['base_n_params']):
            raise ValueError('Duplicate or invalid selection state')
        if any(not _hash(st[key]) for key in _STATE_KEYS if key.endswith('_sha256')):
            raise ValueError('Unbound selection state context')
        if st['family']=='planning':
            if (not st['development_ids'] or set(st['development_ids'])&set(st['public_ids'])
                    or set(st['task_ids'])!=set(st['development_ids']+st['public_ids'])
                    or st['metric_scope']!='selection'):
                raise ValueError('Invalid planning selection task allocation')
        elif (len(st['task_ids'])!=1 or st['development_ids'] or st['public_ids'] or st['metric_scope']!='train'):
            raise ValueError('Invalid symbolic selection task allocation')
        states[st['id']]=st
    if {st['family'] for st in states.values()}!={'planning','symbolic'}:
        raise ValueError('Both task families are required for this selection contract')
    return states


def _measurement(value, *, policy_hash, allocation_hash, state, replicate_id):
    if type(value) is not dict or set(value)!=_MEASUREMENT_KEYS:
        raise ValueError('Invalid measured final fields')
    artifact_bound=_hash(value['source_sha256']) and _params(value['n_params'])
    artifact_absent=(value['status']=='missing' and value['source_sha256'] is None
                     and value['n_params'] is None)
    if (any(not _hash(value[key]) for key in _MEASUREMENT_KEYS
            if key.endswith('_sha256') and key!='source_sha256')
            or value['policy_sha256']!=policy_hash or value['allocation_sha256']!=allocation_hash
            or value['context_sha256']!=_digest(state) or not (artifact_bound or artifact_absent)
            or value['state_id']!=state['id'] or value['replicate_id']!=replicate_id
            or value['evaluation_sha256']!=_digest({k:v for k,v in value.items() if k!='evaluation_sha256'})):
        raise ValueError('Measured final provenance mismatch')
    _ids([value['request_id']])
    if value['status'] not in ('measured','missing','infrastructure_error'):
        raise ValueError('Invalid measured final status')
    if value['status']!='measured':
        if value['results'] is not None:
            raise ValueError('Unmeasured final cannot supply measured results')
        return
    rows=value['results']
    if (type(rows) is not list or len(rows)!=len(state['task_ids'])
            or any(type(row) is not dict or type(row.get('task_id')) is not str for row in rows)
            or len({row['task_id'] for row in rows})!=len(rows)
            or {row['task_id'] for row in rows}!=set(state['task_ids'])):
        raise ValueError('Final evaluation task allocation mismatch')
    for row in rows:
        if 'candidate_hash' in row and row['candidate_hash']!=value['source_sha256']:
            raise ValueError('Evaluation belongs to a different final source')
        for key in ('data_sha256','evaluator_sha256','metric_scope'):
            if key in row and row[key]!=state[key]:
                raise ValueError('Evaluation belongs to a different context')


def select_strategy(parent_policy, candidate_policy, allocation, paired_results):
    """Compare complete paired final outputs from two bound policy snapshots.

Snapshot: {content: object, renderer_sha256, sha256[, policy_id]}; sha256 is
the canonical digest of {content, renderer_sha256}, excluding display labels.
Allocation: {version:'goal-selection-allocation-v0.1', role:'selection', states,
sha256}; its digest excludes only sha256. State keys are documented by
_STATE_KEYS; context_sha256 is the canonical digest of that complete state.
    Every state/replicate slot needs one {state_id, replicate_id, parent,candidate}
    pair. Each side has _MEASUREMENT_KEYS, including state_id, replicate_id and
    a unique request_id; evaluation_sha256 binds all other keys. This prevents
    declared receipt reuse, but the caller must still audit actual requests.
    A missing submission may set both source_sha256 and n_params to None; they
    cannot be omitted individually. Measured and infrastructure_error records
    require a bound artifact. A failure before any artifact exists is recorded
    as missing. All statuses still require request/context/evaluation hashes.

Structural mismatch raises ValueError. Missing/infrastructure measurements
remain unknown. Results are compared directly between the two S finals, never
via each final's improvement flags against an earlier base. All pairs must be
nondegrading and certain, with at least one strict gain, for promotion. These
are conservative development rules, not a significance test or proof of data
authenticity. The caller must verify prior freezing and real evaluation.
"""
    parent_hash=_policy(parent_policy);candidate_hash=_policy(candidate_policy)
    states=_allocation(allocation)
    expected={(st['id'],rep) for st in states.values() for rep in st['replicate_ids']}
    if type(paired_results) is not list or len(paired_results)!=len(expected):
        raise ValueError('Selection pairs do not cover the declared allocation')
    pairs={};request_ids=set()
    for pair in paired_results:
        if type(pair) is not dict or set(pair)!={'state_id','replicate_id','parent','candidate'}:
            raise ValueError('Invalid strategy pair fields')
        if type(pair['state_id']) is not str or type(pair['replicate_id']) is not str:
            raise ValueError('Invalid strategy pair identity')
        key=(pair['state_id'],pair['replicate_id'])
        if key not in expected or key in pairs:
            raise ValueError('Unexpected or duplicate selection pair')
        st=states[pair['state_id']]
        for side,pol in [('parent',parent_hash),('candidate',candidate_hash)]:
            _measurement(pair[side],policy_hash=pol,allocation_hash=allocation['sha256'],state=st,
                replicate_id=pair['replicate_id'])
            if pair[side]['request_id'] in request_ids:
                raise ValueError('Model request reused across selection slots')
            request_ids.add(pair[side]['request_id'])
        pairs[key]=pair
    details=dict(parent_policy_sha256=parent_hash,candidate_policy_sha256=candidate_hash,
        allocation_sha256=allocation['sha256'],pairs=[],
        evidence_boundary='Caller must audit real execution and allocation freeze time; this function only checks supplied records.')
    if parent_hash==candidate_hash:
        return _result('strategy','no_policy_change',['identical_policy_content'],details=details)
    counts={'beneficial_pairs':0,'retained_pairs':0,'regressing_pairs':0,'unknown_pairs':0}
    mapping={'promote':'beneficial_pairs','retain':'retained_pairs','reject':'regressing_pairs','unknown':'unknown_pairs'}
    for st in states.values():
        for rep in st['replicate_ids']:
            pair=pairs[(st['id'],rep)];old=pair['parent'];new=pair['candidate']
            if old['status']!='measured' or new['status']!='measured':
                assessment=_result(st['family'],reasons=['unmeasured_final'],
                    details={'parent_status':old['status'],'candidate_status':new['status']})
            elif st['family']=='planning':
                assessment=assess_planning(old['results'],new['results'],
                    development_ids=st['development_ids'],public_ids=st['public_ids'])
            else:
                oldrow=old['results'][0];newrow=new['results'][0]
                if oldrow.get('status')!='success' or newrow.get('status')!='success':
                    assessment=_result('symbolic',reasons=['symbolic_final_without_complete_numeric_score'],
                        details={'parent_status':oldrow.get('status'),'candidate_status':newrow.get('status')})
                else:
                    oldmetric=oldrow.get('metrics');newmetric=newrow.get('metrics')
                    assessment=assess_symbolic(
                        {'nmse':oldmetric.get('nmse') if type(oldmetric) is dict else None,'n_params':old['n_params']},
                        {'nmse':newmetric.get('nmse') if type(newmetric) is dict else None,'n_params':new['n_params']})
            counts[mapping[assessment['decision']]]+=1
            details['pairs'].append(dict(state_id=st['id'],replicate_id=rep,family=st['family'],
                parent_source_sha256=old['source_sha256'],candidate_source_sha256=new['source_sha256'],
                assessment=assessment))
    if counts['regressing_pairs']:
        decision='retain';reasons=['pair_regression']
    elif counts['unknown_pairs']:
        decision='unknown';reasons=['uncertain_or_unmeasured_pair']
    elif counts['beneficial_pairs']:
        decision='promote';reasons=['paired_benefit_without_regression']
    else:
        decision='retain';reasons=['no_paired_benefit']
    return _result('strategy',decision,reasons,counts,details)
