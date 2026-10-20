"""Pure-stdlib checks of received responses, SDK submissions and budget totals.

This is an audit of saved trusted records, not provider verification. Raw JSON
arguments support only the documented metadata/null/default normalization here.
Other SDK JSON repairs fail closed rather than pretending to replay the SDK.
No candidate source, model, SDK or evaluator is imported or executed.
"""
import copy
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re


def _require(value, reason):
    if not value: raise ValueError(reason)


def _canonical(value):
    return json.dumps(value,ensure_ascii=False,allow_nan=False,
                      sort_keys=True,separators=(',',':')).encode('utf-8')


def _json(text):
    def pairs(items):
        result={}
        for key,value in items:
            _require(key not in result,'Duplicate JSON key')
            result[key]=value
        return result
    def reject(value):raise ValueError('Nonfinite JSON constant')
    return json.loads(text,object_pairs_hook=pairs,parse_constant=reject)


def _read(path):
    path=Path(path)
    _require(not path.is_symlink() and path.is_file(),'Missing or symlinked audit record')
    return _json(path.read_text(encoding='utf-8'))


def _integer(value, label, minimum=0):
    _require(type(value) is int and minimum<=value<=10**12,'Invalid integer: '+label)
    return value


def _number(value,label):
    _require(type(value) in (int,float) and math.isfinite(value) and value>=0,
             'Invalid number: '+label)
    return Decimal(str(value))


def _usage(row):
    usage=row.get('usage')
    _require(row.get('usage_state')=='known' and type(usage) is dict
             and set(usage)=={'prompt_tokens','completion_tokens','total_tokens'},'Known exact usage required')
    for key,value in usage.items():_integer(value,key)
    _require(usage['total_tokens']==usage['prompt_tokens']+usage['completion_tokens'],'Usage token total')
    _require(usage['prompt_tokens']<=_integer(row['input_token_reservation'],'input reservation')
             and usage['completion_tokens']<=_integer(row['output_token_reservation'],'output reservation'),
             'Usage exceeds reservation')
    _require(hashlib.sha256(_canonical(usage)).hexdigest()==row.get('usage_sha256'),'Usage digest')
    return usage


def _normalized_business(raw,stage):
    _require(type(raw) is dict,'Unsupported SDK argument JSON repair')
    value={k:copy.deepcopy(v) for k,v in raw.items()
           if k not in ('summary','security_risk') and v is not None}
    value.setdefault('auxiliary',{})
    if stage=='revision':value.setdefault('rationale','')
    return value


def _valid_business(value,stage):
    try:
        expected=({'probe_id','target_id','auxiliary'} if stage=='probe' else
                  {'source','n_params','rationale','auxiliary'})
        if set(value)!=expected or type(value['auxiliary']) is not dict:return False
        if len(_canonical(value))>65536:return False
        if stage=='probe':
            return all(type(value[k]) is str and 0<len(value[k])<=128 and value[k].strip()
                       for k in ('probe_id','target_id'))
        return (type(value['source']) is str and bool(value['source'].strip())
                and len(value['source'].encode('utf-8'))<=16384
                and type(value['n_params']) is int and 0<=value['n_params']<=16
                and type(value['rationale']) is str and len(value['rationale'])<=4000)
    except (ValueError,TypeError,UnicodeError,OverflowError,RecursionError):return False


def audit_request(directory, request_row, *, stage, session_id, registration=None,candidate=None):
    """Bind one known request, received response and normalized SDK dispatch.

    ``submitted`` means an actual SDK dispatch was recorded. A submitted but
    core-rejected action can still be a missing experimental outcome.
    """
    _require(stage in ('probe','revision'),'Unknown audit stage')
    directory=Path(directory)
    _require(not directory.is_symlink() and not (directory/'requests').is_symlink(),'Symlinked session')
    row=request_row;rid=row.get('request_id')
    _require(type(rid) is str and re.fullmatch(r'request-\d{4}',rid),'Request identifier')
    _require(row.get('session_id')==session_id,'Request/session binding')
    usage=_usage(row)
    payload=_read(directory/'requests'/(rid+'.request.json'))
    encoded=_canonical(payload)
    _require(len(encoded)==row['input_bytes'] and hashlib.sha256(encoded).hexdigest()==row['payload_sha256'],
             'Actual request bytes/digest')
    _require(payload.get('max_output_tokens')==row['output_token_reservation'],'Actual output cap')
    response=_read(directory/'requests'/(rid+'.response.json'))
    _require(_canonical(response.get('usage'))==_canonical(usage),'Received usage differs from ledger')
    expected_status='failed' if row.get('error_type') is not None else 'settled'
    _require(row.get('status')==expected_status,'Ledger status/error mismatch')
    _require(response.get('error_type')==row.get('error_type'),'Received response error differs from ledger')
    choices=response.get('choices');tool='submit_probe' if stage=='probe' else 'submit_candidate'
    calls=None
    if type(choices) is list and len(choices)==1:
        message=choices[0].get('message',{})
        calls=message.get('tool_calls')
    allowed=(type(choices) is list and len(choices)==1 and
             (not calls or type(calls) is list and len(calls)==1
              and calls[0].get('function',{}).get('name') in (tool,'finish')))
    if row.get('error_type')=='PilotResponseContractError':
        _require(not allowed,'Response contract error needs offending choices/tools')
    elif row.get('error_type') is not None:
        raise ValueError('Completed-slot audit does not accept other failed transports')
    else:_require(allowed,'Unauthorized response choices/tools')
    saved_path=directory/'sdk-submission.json';business=None
    called_tool=(calls[0].get('function',{}).get('name') if allowed and calls else None)
    if row.get('error_type') is None and called_tool==tool:
        raw_arguments=calls[0]['function'].get('arguments')
        _require(type(raw_arguments) is str,'Unsupported SDK nonstring argument representation')
        try:business=_normalized_business(_json(raw_arguments),stage)
        except (ValueError,TypeError,UnicodeError,OverflowError,RecursionError) as error:
            raise ValueError('Unsupported raw JSON normalization; audit actual SDK separately') from error
    valid=business is not None and _valid_business(business,stage)
    if saved_path.exists():
        _require(valid,'SDK submission has no matching valid single business call')
        saved=_read(saved_path)
        expected={'stage':stage,'tool':tool,'session_id':session_id,'business':business}
        _require(_canonical(saved)==_canonical(expected),'SDK normalized submission mismatch')
        _require(row['status']=='settled','SDK dispatch after failed transport')
        artifact=registration if stage=='probe' else candidate
        if artifact is None:
            attempts=_read(directory/'attempts.json')
            _require(type(attempts) is list and len(attempts)==1
                     and attempts[0].get('session_id')==session_id
                     and attempts[0].get('status')=='invalid_request','Missing result requires core rejection')
        elif stage=='probe':
            _require(artifact.get('status')=='accepted','Registration status')
            for key in ('probe_id','target_id','auxiliary'):
                _require(_canonical(artifact.get(key))==_canonical(business[key]),'Registration/business '+key)
        else:
            raw_source=(directory/'candidate.py').read_bytes()
            _require(raw_source==business['source'].encode('utf-8'),'Candidate is not SDK-submitted source')
            _require(hashlib.sha256(raw_source).hexdigest()==artifact.get('source_sha256'),'Candidate SHA binding')
            for key in ('n_params','rationale','auxiliary'):
                _require(_canonical(artifact.get(key))==_canonical(business[key]),'Candidate/business '+key)
    else:
        _require(registration is None and candidate is None,'Result without SDK dispatch record')
        _require(not valid,'Valid response business call has no SDK dispatch record')
    return {'status':'passed','submitted':saved_path.exists(),'tool_name':called_tool,
            'request_id':rid,'usage':copy.deepcopy(usage),
            'normalization_scope':'strict_json_metadata_top_level_null_defaults_only'}


def audit_budget(ledger,summary,expected_config):
    """Recompute the complete known-usage BudgetLedger summary with Decimal."""
    config=ledger.get('config')
    _require(config==expected_config,'Budget configuration mismatch')
    for field in ('max_requests','max_requests_per_session','max_output_tokens',
                  'max_input_bytes','max_reserved_tokens'):_integer(config[field],field,1)
    for field in ('max_cost_cny','input_cny_per_million','output_cny_per_million'):
        _require(_number(config[field],field)>0,'Positive price/cost bound required')
    _require(ledger.get('version')==1 and type(ledger.get('version')) is int,'Ledger version')
    _require(ledger.get('halted') is False and ledger.get('halt_reasons')==[]
             and ledger.get('recovery') is None,'Completed round cannot halt/recover')
    sessions=config.get('session_ids')
    _require(type(sessions) is list and 1<=len(sessions)<=16 and len(set(sessions))==len(sessions)
             and all(type(s) is str and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}',s) for s in sessions),
             'Budget session allowlist')
    requests=ledger.get('requests')
    _require(type(requests) is list and len(requests)<=config['max_requests'],'Request count cap')
    def cost(prompt,completion):
        return (Decimal(prompt)*Decimal(str(config['input_cny_per_million']))
                +Decimal(completion)*Decimal(str(config['output_cny_per_million'])))/Decimal(1000000)
    inputs=outputs=prompt=completion=failed=0;session_counts={s:0 for s in sessions}
    for index,row in enumerate(requests,1):
        _require(row.get('request_id')==f'request-{index:04d}','Sequential unique request IDs')
        session=row.get('session_id');_require(session in session_counts,'Unknown budget session')
        session_counts[session]+=1
        _require(session_counts[session]<=config['max_requests_per_session'],'Per-session request cap')
        byte_count=_integer(row['input_bytes'],'input bytes',1)
        inp=_integer(row['input_token_reservation'],'input reservation',1)
        out=_integer(row['output_token_reservation'],'output reservation',1)
        _require(byte_count<=config['max_input_bytes'] and inp==byte_count+8192
                 and out<=config['max_output_tokens'],'Reservation method/caps')
        _require(_number(row['reserved_cost_cny'],'row reserved cost')==cost(inp,out),'Row reserved cost')
        usage=_usage(row)
        _require(_number(row['actual_estimated_cost_cny'],'row known cost')==cost(usage['prompt_tokens'],usage['completion_tokens']),
                 'Row actual estimate')
        error=row.get('error_type')
        _require(error is None or type(error) is str and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}',error),'Error type')
        _require(row.get('status')==('failed' if error is not None else 'settled'),'Settled request status')
        failed+=int(error is not None);inputs+=inp;outputs+=out
        prompt+=usage['prompt_tokens'];completion+=usage['completion_tokens']
    _require(inputs+outputs<=config['max_reserved_tokens'] and cost(inputs,outputs)<=Decimal(str(config['max_cost_cny'])),
             'Cumulative reservation cap')
    computed={'config':copy.deepcopy(config),'request_count':len(requests),'session_counts':session_counts,
        'reserved_count':0,'failed_count':failed,'reserved_input_tokens':inputs,'reserved_output_tokens':outputs,
        'reserved_tokens':inputs+outputs,'reserved_cost_cny':float(cost(inputs,outputs)),
        'usage_unknown_count':0,'known_prompt_tokens':prompt,'known_completion_tokens':completion,
        'known_total_tokens':prompt+completion,'known_estimated_cost_cny':float(cost(prompt,completion)),
        'actual_tokens':prompt+completion,'actual_estimated_cost_cny':float(cost(prompt,completion)),
        'halted':False,'halt_reasons':[],'recovery':None,
        'reservation_method':'compact_utf8_json_bytes_plus_8192',
        'cost_basis':'configured_uncached_prices_estimate_not_provider_invoice'}
    _require(_canonical(summary)==_canonical(computed),'Budget summary totals or fields differ')
    return computed
