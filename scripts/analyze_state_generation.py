#!/usr/bin/env python3
"""Audit frozen cold-start receipts without importing the SDK or executing sources.

This verifies saved records, not provider authenticity. Metadata removal from
strict JSON arguments is supported; undocumented SDK repairs fail closed.
Stopped rounds retain unknown usage and are reported as incomplete evidence.
"""
import argparse
import ast
import copy
from decimal import Decimal
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from rsi_eval.two_stage_audit import _canonical as canonical, _json, _read as read, _require as require, _usage
from rsi_eval.state_generation import build_inputs, validate_config, SLOT_ORDER, PUBLIC_IDS, PROTOCOL


def digest(raw): return hashlib.sha256(raw).hexdigest()


def _path(root, relative, *, directory=False):
    require(type(relative) is str and '\\' not in relative and ':' not in relative, 'Invalid relative path')
    pure = PurePosixPath(relative)
    require(not pure.is_absolute() and '..' not in pure.parts and str(pure) == relative, 'Invalid relative path')
    path = Path(root)
    for part in pure.parts:
        path = path/part
        require(not path.is_symlink() and not (hasattr(path,'is_junction') and path.is_junction()), 'Symlink in audit path')
    require(path.is_dir() if directory else path.is_file(), 'Missing audit input: '+relative)
    return path


def _tree(directory):
    directory = Path(directory); result = {}
    require(directory.is_dir() and not directory.is_symlink(), 'Missing source session tree')
    for path in sorted(directory.rglob('*')):
        require(not path.is_symlink() and not (hasattr(path,'is_junction') and path.is_junction()), 'Symlink in source tree')
        if path.is_file(): result[path.relative_to(directory).as_posix()] = digest(path.read_bytes())
    return result


def _packet(payload):
    messages = payload.get('messages')
    require(type(messages) is list and len(messages) == 2
            and [m.get('role') for m in messages if type(m) is dict] == ['system','user'],
            'Only one frozen system and user packet are allowed')
    require(all(set(m)=={'role','content'} for m in messages),'Unexpected message fields')
    _system_text(messages[0]['content'])
    require(type(messages[1]['content']) is str,'String user packet required')
    return _json(messages[1]['content'])


def _system_text(content):
    if type(content) is str: return content
    require(type(content) is list and len(content)==1 and type(content[0]) is dict
            and set(content[0])=={'type','text'} and content[0]['type']=='text'
            and type(content[0]['text']) is str,'Exactly one SDK system text block required')
    return content[0]['text']


def _business(raw):
    require(type(raw) is dict, 'Unsupported SDK JSON argument repair')
    return {k:copy.deepcopy(v) for k,v in raw.items() if k not in ('summary','security_risk')}


def _valid_business(value):
    try:
        return (type(value) is dict and set(value) == {'source','n_params'}
                and type(value['source']) is str and bool(value['source'].strip())
                and len(value['source'].encode('utf-8')) <= 16384
                and type(value['n_params']) is int and 0 <= value['n_params'] <= 16)
    except (ValueError,TypeError,UnicodeError,OverflowError,RecursionError): return False


def audit_request(directory, row, slot, *, artifact=None, allow_incomplete=False):
    directory = Path(directory); rid = row.get('request_id')
    require(type(rid) is str and re.fullmatch(r'request-\d{4}', rid), 'Request identifier')
    require(row.get('session_id') == slot['id'], 'Request slot binding')
    payload = read(_path(directory, f'requests/{rid}.request.json'))
    require(len(canonical(payload)) == row.get('input_bytes')
            and digest(canonical(payload)) == row.get('payload_sha256'), 'Actual request digest/length')
    require(type(payload.get('max_output_tokens')) is int
            and payload['max_output_tokens'] == row['output_token_reservation'], 'Actual output reservation')
    require(canonical(_packet(payload)) == canonical(slot['packet'])
            == canonical(read(_path(directory,'task-packet.json'))), 'Actual request packet differs from frozen slot')
    response_path = directory/'requests'/f'{rid}.response.json'
    receipt_path = directory/'sdk-submission.json'
    source_path = directory/'source.py'
    incomplete = row.get('usage_state') != 'known' or row.get('status') == 'reserved'
    require(allow_incomplete or not incomplete, 'Unknown/unsettled usage requires incomplete audit')
    if not response_path.exists():
        require(allow_incomplete and row.get('status') == 'reserved' and artifact is None
                and not source_path.exists() and not receipt_path.exists(), 'Missing received response')
        return dict(submitted=False, accepted=False, incomplete=True, request_id=rid,
                    usage=None, tool_name=None, normalization_scope='no_response')
    response = read(_path(directory,f'requests/{rid}.response.json'))
    usage = _usage(row) if not incomplete else None
    raw_usage = response.get('usage')
    require(response.get('error_type') == row.get('error_type'), 'Received error differs from ledger')
    if usage is not None:
        require(canonical(raw_usage) == canonical(usage), 'Received usage differs from ledger')
    else:
        require(digest(canonical(raw_usage)) == row.get('usage_sha256'), 'Unknown/invalid raw usage digest')
        require(row.get('usage') is None, 'Unknown usage cannot supply normalized totals')
    require(row.get('status') == ('failed' if row.get('error_type') is not None else 'settled'), 'Request settlement status')
    choices = response.get('choices'); calls = None; shape = False
    if type(choices) is list and len(choices) == 1 and type(choices[0]) is dict:
        message = choices[0].get('message')
        if type(message) is dict: shape = True; calls = message.get('tool_calls')
    allowed = shape and (not calls or type(calls) is list and len(calls)==1
        and type(calls[0]) is dict and type(calls[0].get('function')) is dict
        and calls[0]['function'].get('name') in ('submit_candidate','finish'))
    error = row.get('error_type')
    if error == 'PilotResponseContractError':
        require(not allowed, 'Response contract error lacks offending response')
    elif error is None:
        require(allowed, 'Unauthorized response choices/tools')
    else:
        require(allow_incomplete, 'Transport error requires stopped evidence')
        incomplete = True
    called = calls[0]['function'].get('name') if allowed and calls else None
    business = None
    if error is None and called == 'submit_candidate':
        arguments = calls[0]['function'].get('arguments')
        require(type(arguments) is str, 'Unsupported SDK non-string arguments')
        try: business = _business(_json(arguments))
        except (ValueError,TypeError,UnicodeError,OverflowError,RecursionError) as exc:
            if receipt_path.exists():
                raise ValueError('Unsupported SDK raw JSON normalization') from exc
            business = None
    valid = _valid_business(business)
    if receipt_path.exists():
        require(valid and error is None, 'SDK receipt lacks matching valid business call')
        expected = dict(stage='generation',tool='submit_candidate',session_id=slot['id'],business=business)
        require(canonical(read(_path(directory,'sdk-submission.json'))) == canonical(expected), 'SDK business receipt differs')
        if artifact is not None:
            require(not incomplete, 'Unsettled or unknown usage cannot accept a source')
            require(artifact == read(_path(directory,'candidate.json')), 'Summary/candidate binding')
            expected_candidate = dict(version='state-generation-v0.1',slot_id=slot['id'],family=slot['family'],
                origin='model_generated_without_task_feedback',status='stored_unexecuted',source_file='source.py',
                source_sha256=digest(business['source'].encode()),n_params=business['n_params'],packet_sha256=slot['packet_sha256'])
            require(canonical(artifact)==canonical(expected_candidate), 'Accepted source metadata differs')
            require(slot['family']!='planning' or business['n_params']==0, 'Planning parameter count')
            require(_path(directory,'source.py').read_bytes()==business['source'].encode('utf-8'), 'SDK/source byte mismatch')
            attempt = read(_path(directory,'submission-attempt.json'))
            require(attempt == dict(session_id=slot['id'],status='accepted',source_sha256=artifact['source_sha256']),
                    'Accepted source attempt receipt')
        else:
            require(not source_path.exists() and not (directory/'candidate.json').exists(), 'Missing artifact has source files')
            if (directory/'controller-error.json').exists():
                require(allow_incomplete, 'Controller infrastructure error requires incomplete audit')
                controller_error=read(_path(directory,'controller-error.json'))
                require(controller_error.get('status')=='infrastructure_error'
                        and controller_error.get('stage')=='generation', 'Controller error binding')
                incomplete=True
            else:
                attempt=read(_path(directory,'submission-attempt.json'))
                require(attempt==dict(session_id=slot['id'],status='invalid_request',error_kind='source_submission_contract'),
                        'Missing source requires explicit core rejection')
                require(slot['family']=='planning' and business['n_params']!=0, 'Unexplained core rejection')
    else:
        require(artifact is None and not source_path.exists() and not (directory/'candidate.json').exists(), 'Source without SDK dispatch')
        require(not valid or allow_incomplete, 'Valid response has no SDK receipt')
        if valid: incomplete=True
    return dict(submitted=receipt_path.exists(),accepted=artifact is not None,incomplete=incomplete,
        request_id=rid,usage=usage,tool_name=called,normalization_scope='strict_json_sdk_metadata_removal_only')


def audit_budget_state(ledger, summary, expected_config, *, allow_incomplete=False):
    require(ledger.get('config')==expected_config and type(ledger.get('version')) is int
            and ledger['version']==1, 'Budget configuration/version')
    require(ledger.get('recovery') is None, 'No recovery in source generation')
    config=ledger['config']; rows=ledger.get('requests')
    require(type(rows) is list and len(rows)<=config['max_requests'], 'Request cap')
    sessions=config['session_ids']; per={s:0 for s in sessions}
    def integer(v): require(type(v) is int and 0<=v<=10**12,'Invalid budget integer'); return v
    def cost(i,o):
        return (Decimal(i)*Decimal(str(config['input_cny_per_million']))+Decimal(o)*Decimal(str(config['output_cny_per_million'])))/Decimal(1000000)
    inputs=outputs=prompt=completion=unknown=failed=reserved=0; reasons=set(); found_incomplete=False
    for index,row in enumerate(rows,1):
        require(row.get('request_id')==f'request-{index:04d}' and row.get('session_id') in per,'Budget slot/sequence')
        per[row['session_id']]+=1
        require(per[row['session_id']]<=config['max_requests_per_session'],'Per-slot request cap')
        size=integer(row.get('input_bytes')); inp=integer(row.get('input_token_reservation')); out=integer(row.get('output_token_reservation'))
        require(0<size<=config['max_input_bytes'] and inp==size+8192 and 0<out<=config['max_output_tokens'],'Reservation size/cap')
        require(Decimal(str(row.get('reserved_cost_cny')))==cost(inp,out),'Reservation cost')
        inputs+=inp;outputs+=out
        require(not found_incomplete,'Request after unknown/unsettled/invalid usage')
        if row.get('usage_state')=='known':
            usage=_usage(row);prompt+=usage['prompt_tokens'];completion+=usage['completion_tokens']
            require(Decimal(str(row.get('actual_estimated_cost_cny')))==cost(usage['prompt_tokens'],usage['completion_tokens']),'Known cost')
        else:
            require(allow_incomplete and row.get('usage_state') in ('unknown','invalid')
                    and row.get('usage') is None and row.get('actual_estimated_cost_cny') is None,'Unknown usage scope')
            unknown+=1;found_incomplete=True
            if row.get('status')!='reserved': reasons.add('usage_unknown' if row['usage_state']=='unknown' else 'invalid_usage')
        error=row.get('error_type')
        require(error is None or type(error) is str and re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,127}',error),'Error class')
        status=row.get('status')
        if status=='reserved':
            require(allow_incomplete and row['usage_state']=='unknown' and error is None,'Reserved request scope');reserved+=1
        else: require(status==('failed' if error is not None else 'settled'),'Settlement error/status')
        failed+=int(status=='failed')
    require(inputs+outputs<=config['max_reserved_tokens'] and cost(inputs,outputs)<=Decimal(str(config['max_cost_cny'])),'Total reservation cap')
    require(type(ledger.get('halted')) is bool and ledger['halted']==bool(reasons)
            and ledger.get('halt_reasons')==sorted(reasons),'Budget halt reasons')
    computed=dict(config=copy.deepcopy(config),request_count=len(rows),session_counts=per,reserved_count=reserved,
        failed_count=failed,reserved_input_tokens=inputs,reserved_output_tokens=outputs,reserved_tokens=inputs+outputs,
        reserved_cost_cny=float(cost(inputs,outputs)),usage_unknown_count=unknown,
        known_prompt_tokens=prompt,known_completion_tokens=completion,known_total_tokens=prompt+completion,
        known_estimated_cost_cny=float(cost(prompt,completion)),actual_tokens=None if unknown else prompt+completion,
        actual_estimated_cost_cny=None if unknown else float(cost(prompt,completion)),halted=ledger['halted'],
        halt_reasons=ledger['halt_reasons'],recovery=None,reservation_method='compact_utf8_json_bytes_plus_8192',
        cost_basis='configured_uncached_prices_estimate_not_provider_invoice')
    require(canonical(summary)==canonical(computed),'Budget summary differs')
    return computed


def _runtime(root, freeze, report):
    commit=freeze.get('runtime_commit')
    require(type(commit) is str and re.fullmatch('[0-9a-f]{40}',commit)
            and report.get('runtime_commit')==commit and freeze.get('checkout_clean') is True,'Clean runtime anchor')
    mapping=freeze.get('runtime_files_sha256')
    required={PROTOCOL,'rsi_eval/state_generation.py','rsi_eval/state_generation_agent.py',
        'scripts/run_state_generation.py','scripts/analyze_state_generation.py',
        'configs/pilots/state-generation-v0.1.json','tests/test_state_generation_audit.py'}
    require(type(mapping) is dict and required<=set(mapping),'Runtime inventory incomplete')
    names=subprocess.check_output(['git','-C',str(root),'ls-tree','-r','-z','--name-only',commit,
        '--','rsi_eval','scripts','configs','prompts','fixtures','tests']).decode('utf-8').split('\0')
    expected={name for name in names if name and (name.split('/',1)[0] in ('rsi_eval','scripts','configs','prompts','fixtures')
        and Path(name).suffix in ('.py','.json','.md','.txt')
        or name.startswith('tests/test_state_generation') and name.endswith('.py'))}
    expected.update({PROTOCOL,'docs/protocols/2026-10-21-two-stage-v0.1.md'})
    require(set(mapping)==expected,'Complete runtime file inventory differs from Git')
    for name, expected in mapping.items():
        path=_path(root,name)
        blob=subprocess.check_output(['git','-C',str(root),'show',commit+':'+name])
        require(digest(blob)==expected==digest(path.read_bytes()),'Frozen runtime differs: '+name)
    return commit


def _history(root, value, commit):
    require(set(value)=={'version','files'} and value['version']=='history-source-index-v0.1','Historical index version')
    names=subprocess.check_output(['git','-C',str(root),'ls-tree','-r','-z','--name-only',commit,'--','artifacts']).decode('utf-8').split('\0')
    expected_names={name for name in names if name.endswith('.py')}
    require(set(value['files'])==expected_names,'Historical source inventory differs from runtime Git tree')
    from scripts.run_state_generation import ast_digest
    for name, info in value['files'].items():
        raw=_path(root,name).read_bytes()
        blob=subprocess.check_output(['git','-C',str(root),'show',commit+':'+name])
        require(raw==blob,'Historical source differs from frozen commit')
        try: normalized=ast_digest(raw.decode('utf-8'))
        except UnicodeError: normalized=None
        require(info==dict(source_sha256=digest(raw),ast_sha256=normalized),'Historical source/AST index differs')


def _literal_constants(root):
    tree=ast.parse(_path(root,'rsi_eval/state_generation_agent.py').read_text(encoding='utf-8'))
    wanted={'GENERATION_SYSTEM_PROMPT','TOOL_DESCRIPTION'}; result={}
    for node in tree.body:
        if isinstance(node,ast.Assign):
            for target in node.targets:
                if isinstance(target,ast.Name) and target.id in wanted:
                    require(isinstance(node.value,ast.Constant) and type(node.value.value) is str,'Adapter prompt must be literal')
                    result[target.id]=node.value.value
    require(set(result)==wanted,'Missing literal adapter contract')
    return result


def _actual_contract(root, directory, row, slot, model, *, allow_incomplete=False):
    rid=row['request_id'];payload=read(_path(directory,f'requests/{rid}.request.json'))
    constants=_literal_constants(root)
    require(payload.get('model')==model and _system_text(payload['messages'][0]['content'])==constants['GENERATION_SYSTEM_PROMPT'],
            'Actual model/system differs')
    tools=payload.get('tools')
    require(type(tools) is list and len(tools)==2 and all(type(t) is dict and type(t.get('function')) is dict for t in tools),
            'Two declared tools required')
    by={t['function'].get('name'):t['function'] for t in tools}
    require(set(by)=={'submit_candidate','finish'},'Actual tool allowlist')
    tool=by['submit_candidate'];parameters=tool.get('parameters',{});props=parameters.get('properties',{})
    require(tool.get('description')==constants['TOOL_DESCRIPTION']
            and set(props)-{'summary','security_risk'}=={'source','n_params'}
            and {'source','n_params'}<=set(parameters.get('required',[]))
            and props['source'].get('type')=='string' and props['n_params'].get('type')=='integer'
            and props['n_params'].get('minimum')==0 and props['n_params'].get('maximum')==16,
            'Actual source submission schema')
    input_audit=read(_path(directory,'requests/input-audit-0001.json'))
    require(input_audit.get('version')=='input-audit-v0.1' and input_audit.get('attempt_index')==1
            and input_audit.get('session_id')==slot['id']
            and input_audit.get('actual_input_bytes')==row['input_bytes']
            and input_audit.get('payload_sha256')==row['payload_sha256']
            and input_audit.get('max_input_bytes')==65536 and input_audit.get('excess_bytes')==0
            and input_audit.get('request_reserved') is True,'Input audit binding')
    dispatched=input_audit.get('network_dispatch_attempted')
    require(type(dispatched) is bool and input_audit.get('transport_called') is dispatched,
            'Input audit transport flags')
    require(input_audit.get('request_id')==rid or allow_incomplete and not dispatched
            and input_audit.get('request_id') is None,'Input audit reservation ID')
    require(dispatched or allow_incomplete,'Completed source request was never dispatched')
    require(canonical(read(_path(directory,'requests/packet-0001.json')))==canonical(slot['packet']),'Actual packet audit')
    return payload


def audit(root, run):
    root=Path(root).resolve();run=Path(run).resolve()
    require(not run.is_symlink(),'Symlinked run')
    report=read(_path(run,'summary.json'));config=validate_config(read(_path(run,'config.json')))
    status=report.get('status')
    require(report.get('version')=='state-generation-run-v0.1'
            and status in ('attempts_completed','stopped','prepared'),'Unsupported source run status')
    incomplete=status=='stopped';prepared=status=='prepared'
    commit=_runtime(root,read(_path(run,'runtime-freeze.json')),report)
    inputs=read(_path(run,'input-freeze.json'))
    require(digest((run/'input-freeze.json').read_bytes())==report.get('inputs_freeze_sha256'),'Input freeze hash')
    examples=[dict(family='planning',task_id=task,**example) for task,example in
              zip(PUBLIC_IDS,inputs['slots'][0]['packet']['examples'])]
    require(canonical(inputs)==canonical(build_inputs(root,examples)) and inputs['config']==config,'Frozen source inputs')
    history=read(_path(run,'history-index.json'))
    require(digest((run/'history-index.json').read_bytes())==report.get('history_index_sha256'),'History index hash')
    _history(root,history,commit)
    from scripts.run_checked_feedback import _model_configuration
    model_digest,public,effective=_model_configuration(_path(root,'configs/models/minimax-m3.json'),config['budgets'])
    require(report.get('model_config_sha256')==model_digest and report.get('model_config')==public
            and report.get('effective_model_config')==effective,'Model configuration binding')
    require(read(_path(run,'generation-settings.json'))==dict(model_config_sha256=model_digest,public=public,effective=effective),
            'Saved generation settings')
    rows=report.get('slots');slots=inputs['slots'];identity=('id','family','role','task_ids','input_dimension')
    require(type(rows) is list and [{k:r.get(k) for k in identity} for r in rows]==[{k:s[k] for k in identity} for s in slots],
            'Full frozen slot allocation')
    ledger=read(_path(run,'budget-ledger.json'))
    budget=audit_budget_state(ledger,report.get('budget'),dict(config['budgets'],session_ids=SLOT_ORDER),allow_incomplete=incomplete)
    requests=ledger['requests'];by={r['session_id']:r for r in requests}
    require([r['session_id'] for r in requests]==SLOT_ORDER[:len(requests)],'Request order/prefix')
    for key in ('candidate_executions','task_evaluations','probe_executions','sealed_tasks_executed','strategy_updates'):
        require(type(report.get(key)) is int and report[key]==0,'Zero-scope '+key)
    for key in ('model_weight_updates','symbolic_csv_reads'):
        if key in report: require(type(report[key]) is int and report[key]==0,'Zero-scope '+key)
    require(report.get('resumed') is False,'No resume')
    if prepared:
        require(not requests and all(r.get('disposition')=='not_started' and r.get('candidate') is None for r in rows),
                'Prepared run has attempts')
        return dict(status='prepared_checked',run_status=status,allocation_completed=False,runtime_commit=commit,
            model_requests=0,accepted_sources=0,known_tokens=0,known_estimated_cost_cny=0)
    frozen=read(_path(run,'source-freeze.json'))
    require(digest((run/'source-freeze.json').read_bytes())==report.get('source_freeze_sha256'),'Source phase hash')
    require(frozen==dict(version='source-freeze-v0.1',inputs_freeze_sha256=report['inputs_freeze_sha256'],
        history_index_sha256=report['history_index_sha256'],runtime_commit=commit,slots=rows,
        session_files=_tree(_path(run,'sessions',directory=True))),'Frozen source inventory/slot binding')
    proofs={};receipts=[];available=0;started=set();blocked=False
    for row,slot in zip(rows,slots):
        name=slot['id'];directory=run/'sessions'/name;request=by.get(name)
        if request is None:
            require(row.get('request_id') is None and row.get('candidate') is None,'Missing request has accepted artifact')
            require(incomplete,'Completed allocation has missing request')
            if directory.exists():
                require(not blocked and row.get('disposition')=='blocked','Unexpected unrequested session')
                require(not (directory/'source.py').exists() and not (directory/'candidate.json').exists()
                        and not (directory/'sdk-submission.json').exists(),'Unrequested session has source/dispatch')
                session=read(_path(directory,'session-summary.json'))
                require(row.get('session_summary')==session and session.get('session_id')==name
                        and session.get('stage')=='generation' and session.get('status')=='error'
                        and session.get('model_error_type') is not None,'Unrequested slot lacks host-error evidence')
                started.add(name);blocked=True
            else: require(row.get('disposition')=='not_started' and row.get('session_summary') is None,'Unstarted slot status')
            continue
        require(not blocked and row.get('request_id')==request['request_id'],'Request after blocked slot or wrong ID')
        started.add(name)
        receipt=audit_request(directory,request,slot,artifact=row.get('candidate'),allow_incomplete=incomplete)
        payload=_actual_contract(root,directory,request,slot,effective['model'],allow_incomplete=incomplete)
        require(row.get('session_summary')==read(_path(directory,'session-summary.json')),'Session summary binding')
        session=row['session_summary']
        require(session.get('session_id')==name and session.get('stage')=='generation'
                and session.get('adapter_version')=='state-generation-agent-v0.1'
                and session.get('sdk_version')=='1.55.1' and set(session.get('tools',[]))=={'submit_candidate','finish'},
                'Session adapter/tools binding')
        controller=session.get('controller')
        require(type(controller) is dict and controller.get('candidate')==row.get('candidate')
                and controller.get('slot_id')==name,'Session controller binding')
        for field in ('candidate_executions','task_scores','sealed_tasks_executed','strategy_updates','model_calls_owned'):
            require(type(controller.get(field)) is int and controller[field]==0,'Controller zero scope')
        disposition=row.get('disposition')
        if disposition=='blocked': require(incomplete,'Completed slot cannot be blocked');blocked=True
        else: require(disposition==('available' if row.get('candidate') is not None else 'missing') and not receipt['incomplete'],
                      'Slot disposition contradicts evidence')
        dispatched=read(_path(directory,'requests/input-audit-0001.json'))['network_dispatch_attempted']
        available+=row.get('candidate') is not None
        receipts.append(dict(slot_id=name,network_dispatch_attempted=dispatched,**receipt))
        grouping='planning' if slot['family']=='planning' else 'symbolic-'+str(slot['input_dimension'])
        proofs.setdefault(grouping,[]).append(digest(canonical(payload)))
    require({p.name for p in (run/'sessions').iterdir()}==started,'Unexpected source session directory')
    require(len(list((run/'sessions').rglob('*.request.json')))==len(requests),'Raw request file cardinality')
    if not incomplete: require(len(requests)==8 and not blocked,'Complete allocation needs eight attempts')
    else: require(blocked or budget['usage_unknown_count'] or budget['reserved_count'],'Stopped run lacks stop evidence')
    require(all(len(set(values))==1 for values in proofs.values()),'Equal-information actual requests differ')
    from scripts.run_state_generation import analyze_frozen_sources
    analysis=read(_path(run,'static-analysis.json'))
    require(digest((run/'static-analysis.json').read_bytes())==report.get('analysis_sha256')
            and canonical(analysis)==canonical(analyze_frozen_sources(run)),'Recomputed static analysis differs')
    require(report.get('source_counts')=={k:analysis[k] for k in ('source_slots','available_sources','distinct_source_count','distinct_ast_count')},
            'Static summary counts')
    return dict(status='record_consistent_incomplete' if incomplete else 'passed',run_status=status,
        allocation_completed=not incomplete,runtime_commit=commit,model_requests=len(requests),accepted_sources=available,
        request_reservations=len(requests),transport_dispatch_attempts=sum(r['network_dispatch_attempted'] for r in receipts),
        missing_or_unattempted_sources=8-available,known_tokens=budget['known_total_tokens'],
        known_estimated_cost_cny=budget['known_estimated_cost_cny'],actual_estimated_cost_cny=budget['actual_estimated_cost_cny'],
        reserved_cost_cny=budget['reserved_cost_cny'],unknown_usage_requests=budget['usage_unknown_count'],
        history_source_files=len(history['files']),frozen_session_files=len(frozen['session_files']),
        source_freeze_sha256=report['source_freeze_sha256'],analysis_sha256=report['analysis_sha256'],
        common_request_sha256={k:v[0] for k,v in sorted(proofs.items())},receipts=receipts,static_analysis=analysis,
        candidate_executions=0,task_evaluations=0,probe_executions=0,sealed_tasks_executed=0,strategy_updates=0,
        limitations=['Saved trusted records verified; no provider authenticity or independent timestamp attestation.',
            'Strict JSON plus SDK metadata removal only; no claim to replay other SDK argument repairs.',
            'No candidate execution, task performance measurement, strategy update, or independent-state guarantee.',
            'Stopped evidence remains incomplete; missing or unknown usage is not counted as zero.'])


def write_output(root,path,result):
    root=Path(root).resolve();path=Path(path)
    if not path.is_absolute(): path=root/path
    require(not any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in (path,*path.parents)),
            'Symlink in output path')
    path=path.resolve()
    require(path.suffix=='.json' and any(path.is_relative_to(root/base) for base in ('tmp','docs/analysis')),'Invalid audit output scope')
    raw=(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
    if path.exists(): require(path.read_bytes()==raw,'Refusing to overwrite different audit result')
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream: stream.write(raw)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-dir',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();result=audit(ROOT,Path(args.run_dir));write_output(ROOT,args.output,result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('receipts','static_analysis')},indent=2))


if __name__=='__main__': main()
