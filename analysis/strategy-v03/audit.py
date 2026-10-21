"""Read only the pinned v03 archive. Never import/execute candidate programs.

Run from the repository root. Output is descriptive, not a new evaluation or
statistical significance test. Standard library only; no runtime dependencies.
"""
import argparse
import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

ARCHIVE = 'artifacts/strategy-measured/2026-10-21/v03'
MANIFEST_SHA256 = 'a4ca888e054d8a84873f7fc91fe4f803a3ab814b9107d27e3ba46299a27de0e4'


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def sha(data):
    return hashlib.sha256(data).hexdigest()


class WithoutDocstrings(ast.NodeTransformer):
    def strip(self, node):
        self.generic_visit(node)
        if (node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)):
            node.body = node.body[1:]
        return node

    visit_Module = strip
    visit_ClassDef = strip
    visit_FunctionDef = strip
    visit_AsyncFunctionDef = strip


def source_facts(source):
    out = {'source_sha256': sha(source.encode('utf-8'))}
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return dict(out, syntax_valid=False, syntax_error_line=error.lineno)
    out.update(syntax_valid=True, ast_sha256=sha(ast.dump(tree).encode()))
    out['ast_without_docstrings_sha256'] = sha(ast.dump(WithoutDocstrings().visit(tree)).encode())
    return out


def summarize_rows(rows):
    if not rows:
        raise ValueError('Empty generation group')
    if len({tuple(r['task_ids']) for r in rows}) != 1:
        raise ValueError('Group task IDs differ')
    if len({r.get('evaluation_identity') for r in rows}) != 1:
        raise ValueError('Group task data/evaluator identities differ')
    if len({(r['family'], r['state_id'], r['policy_sha256']) for r in rows}) != 1:
        raise ValueError('Group state/policy/family differs')
    scores = [r['nmse'] for r in rows if r.get('nmse') is not None]
    successes = [r['successes'] for r in rows]
    out = dict(n_generations=len(rows), slots=[r['slot_id'] for r in rows],
               state_id=rows[0]['state_id'], family=rows[0]['family'],
               policy_sha256=rows[0]['policy_sha256'],
               tasks_per_generation=len(rows[0]['task_ids']),
               unique_source_bytes=len({r['source_sha256'] for r in rows}),
               successes=successes, successes_range=[min(successes), max(successes)],
               numeric_nmse_count=len(scores), missing_nmse_count=len(rows)-len(scores),
               nmse_values=[r.get('nmse') for r in rows],
               nmse_range=[min(scores), max(scores)] if scores else None)
    if out['family'] == 'planning':
        out['missing_nmse_count'] = 0  # NMSE is not applicable, not a failure.
    return out


def group_rows(rows):
    if len({r['slot_id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate generation')
    groups = defaultdict(list)
    for row in rows:
        groups[row['request_sha256'], row.get('transport_sha256')].append(row)
    return [dict(summarize_rows(items), request_sha256=key[0], transport_sha256=key[1])
            for key, items in sorted(groups.items(), key=lambda pair: pair[0][0])]


def transport_identity(dispatch, transport, request_ref):
    relative = 'requests/' + Path(request_ref['path']).name
    for record in (dispatch, transport):
        if record['request_sha256'] != request_ref['sha256'] or record['request_file'] != relative:
            raise ValueError('Transport request binding mismatch')
    fields = {k:v for k,v in transport.items() if k not in ('request_file','request_sha256')}
    return sha(canonical({'observed_dispatch':dispatch['observed'], 'transport':fields,
                          'settings_sha256':dispatch.get('settings_sha256')}))


class FrozenArchive:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.base = self.root / ARCHIVE
        raw = (self.base / 'manifest.json').read_bytes()
        if sha(raw) != MANIFEST_SHA256:
            raise ValueError('Archive manifest changed')
        self.manifest = json.loads(raw)
        self.verify()

    def path(self, name):
        path = self.base / name
        if path.is_symlink() or not path.resolve().is_relative_to(self.base.resolve()):
            raise ValueError('Archive path escapes scope')
        if name not in self.manifest['files']:
            raise ValueError('Unlisted archive file')
        return path

    def verify(self):
        if {p.relative_to(self.base).as_posix() for p in self.base.rglob('*') if p.is_file()} != set(self.manifest['files']) | {'manifest.json'}:
            raise ValueError('Archive inventory changed')
        for name, digest in self.manifest['files'].items():
            if sha(self.path(name).read_bytes()) != digest:
                raise ValueError('Archive content changed: ' + name)

    def read(self, name):
        return json.loads(self.path(name).read_bytes())

    def reference(self, ref, *, text=False):
        name = self.manifest['source_map'][ref['path']]
        raw = self.path(name).read_bytes()
        if sha(raw) != ref['sha256']:
            raise ValueError('Reference hash mismatch')
        return raw.decode('utf-8') if text else json.loads(raw)

    def archived_path(self, original):
        return ARCHIVE + '/' + self.manifest['source_map'][original]


def packet_from_request(request):
    users = [m for m in request['messages'] if m['role'] == 'user']
    if len(users) != 1:
        raise ValueError('Expected one user packet')
    content = users[0]['content']
    if isinstance(content, list):
        if len(content) != 1 or content[0]['type'] != 'text':
            raise ValueError('Unexpected message parts')
        content = content[0]['text']
    return json.loads(content)


def analyze(root):
    archive = FrozenArchive(root)
    summary = archive.read('raw/experiment/summary.json')
    if summary['status'] != 'complete' or summary['evidence_kind'] != 'observed':
        raise ValueError('Expected complete observed run')
    prior = archive.read('verification/strategy-measured-v03-analysis.json')
    renderer = archive.read('raw/experiment/parent-policy.json')['renderer_sha256']
    requests = {r['slot_id']: r for r in prior['requests']}
    measurements = defaultdict(list)
    for event in summary['events']:
        if event['kind'] == 'measurement_recorded':
            record = archive.reference(event['receipt'])
            measurements[record['candidate_id']].append(record)
    rows = []
    for item in summary['slots']:
        slot, session = item['slot'], item['session']
        if slot['phase'] == 'update':
            continue
        if item['status'] != 'completed' or session['status'] != 'accepted':
            raise ValueError('Actor is incomplete')
        request = archive.reference(session['request'])
        packet = packet_from_request(request)
        state = packet['current_state']
        child = source_facts(archive.reference(session['source'], text=True))
        parent = source_facts(state['source'])
        if parent['source_sha256'] != state['source_sha256']:
            raise ValueError('Parent source hash mismatch')
        records = sorted(measurements[slot['id']], key=lambda r: r['task_id'])
        if not records or len({r['task_id'] for r in records}) != len(records):
            raise ValueError('Missing or duplicate task measurements')
        if any(r['candidate_hash'] != child['source_sha256'] for r in records):
            raise ValueError('Measurement/source binding differs')
        submission = archive.reference(session['submission'])
        response = archive.reference(session['response'])
        calls = response['choices'][0]['message']['tool_calls']
        if len(calls) != 1:
            raise ValueError('Unexpected response calls')
        arguments = json.loads(calls[0]['function']['arguments'])
        same_bytes = child['source_sha256'] == parent['source_sha256']
        same_ast = child.get('ast_sha256') == parent.get('ast_sha256') and child['syntax_valid'] and parent['syntax_valid']
        same_body = child.get('ast_without_docstrings_sha256') == parent.get('ast_without_docstrings_sha256') and child['syntax_valid'] and parent['syntax_valid']
        nmse = records[0].get('metrics', {}).get('nmse') if state['family'] == 'symbolic' and records[0]['status'] == 'success' else None
        row = dict(slot_id=slot['id'], phase=slot['phase'], replicate=slot['replicate'], arm=slot['arm'],
                   state_id=slot['state_id'], family=state['family'], policy=packet['repair_policy'],
                   policy_sha256=sha(canonical({'content':{k:packet['repair_policy'][k] for k in ('version','rule_ids')},
                                               'renderer_sha256':renderer})),
                   rendered_policy_sha256=sha(canonical(packet['repair_policy'])),
                   request_sha256=session['request']['sha256'],
                   transport_sha256=transport_identity(
                       archive.read('raw/experiment/sessions/'+slot['id']+'/sdk-dispatch.json'),
                       archive.read('raw/experiment/sessions/'+slot['id']+'/transport-request.json'),session['request']),
                   source_sha256=child['source_sha256'], source_path=archive.archived_path(session['source']['path']),
                   request_path=archive.archived_path(session['request']['path']),
                   response_path=archive.archived_path(session['response']['path']),
                   parent_source=parent, child_source=child, source_bytes_equal_parent=same_bytes,
                   ast_equal_parent=same_ast, ast_without_docstrings_equal_parent=same_body,
                   edit_class='bytes_identical' if same_bytes else 'ast_identical' if same_ast else 'docstring_only_ast' if same_body else 'ast_changed',
                   n_params=submission['n_params'], parent_n_params=state['n_params'],
                   explanation=arguments.get('explanation'),
                   task_ids=[r['task_id'] for r in records],
                   evaluation_identity=sha(canonical([{k:r[k] for k in ('task_id','data_sha256','evaluator_sha256','metric_scope')} for r in records])),
                   successes=sum(r['status']=='success' for r in records),
                   statuses=dict(sorted(Counter(r['status'] for r in records).items())), nmse=nmse)
        expected_count = 1 if state['family']=='symbolic' else 19 if slot['phase']=='selection' else 63
        if len(records) != expected_count:
            raise ValueError('Unexpected measurement count')
        for record in records:
            if (row['n_params'] != record['n_params'] or state['family'] != record['family']
                    or record['strategy_version'] != row['policy_sha256']):
                raise ValueError('Measurement parameter/policy/family binding differs')
        rows.append(row)
    states={'selection':['P-select-1','P-select-2','S-select-1','S-select-2'],
            'evaluation':['P-eval-1','P-eval-2','S-bact-eval-1','S-stress-eval-1']}
    expected={f'{rep}-{phase}-{state}-{arm}' for rep in ('r1','r2') for phase,items in states.items()
              for state in items for arm in ('fixed','updated')}
    if len(rows) != 32 or {r['slot_id'] for r in rows} != expected or sum(len(v) for v in measurements.values()) != 716:
        raise ValueError('Incomplete population')
    rows.sort(key=lambda r:r['slot_id'])
    groups = group_rows(rows)
    pairs = []
    by_slot = {r['slot_id']:r for r in rows}
    for pair in prior['pairs']:
        left, right = (by_slot[pair['arm_slots'][arm]] for arm in ('fixed', 'updated'))
        if left['task_ids'] != right['task_ids'] or left['evaluation_identity'] != right['evaluation_identity']:
            raise ValueError('Pair task identities differ')
        numeric = left['nmse'] is not None and right['nmse'] is not None
        pairs.append(dict(replicate=pair['replicate'], phase=pair['phase'], state_id=pair['state_id'],
                          same_policy=left['policy']==right['policy'],
                          fixed_slot=left['slot_id'], updated_slot=right['slot_id'],
                          saved_assessment=pair['goal_assessment']['decision'],
                          n_params_delta=right['n_params']-left['n_params'],
                          nmse_decrease=left['nmse']-right['nmse'] if numeric else None,
                          successes_delta=right['successes']-left['successes']))
    covered=[p[k] for p in pairs for k in ('fixed_slot','updated_slot')]
    if len(pairs)!=16 or len(set(covered))!=32 or set(covered)!=expected:
        raise ValueError('Pair population differs')
    archive.verify()
    return dict(version='strategy-offline-audit-v0.1', status='passed', archive=ARCHIVE,
                manifest_sha256=MANIFEST_SHA256, archive_files_verified=len(archive.manifest['files'])+1,
                observed_measurements_reused=716, actor_generations=32,
                source_edit_counts=dict(sorted(Counter(r['edit_class'] for r in rows).items())),
                groups=groups, repeated_groups=[g for g in groups if g['n_generations']>1],
                actors=rows, pairs=pairs,
                new_activity=dict(model_requests=0,candidate_executions=0,fits=0,sealed_accesses=0),
                limitations=['Post-hoc descriptive analysis; no significance or causal estimate.',
                             'AST equality excluding docstrings is syntactic, not general semantic equivalence.',
                             'Same saved request and transport settings do not certify provider determinism or independence.',
                             'saved_assessment quotes the pinned prior audit; it is not independently reselected here.',
                             'Task vectors are repeated measurements of one generated program, not independent policy learning.'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    output=(root/args.output).resolve()
    if not any(output.is_relative_to(root/p) for p in ('tmp','analysis/strategy-v03')):
        raise ValueError('Output must be in tmp or analysis/strategy-v03')
    report=analyze(root)
    raw=json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False).encode('utf-8')+b'\n'
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('xb') as stream:
        stream.write(raw)
    print(json.dumps({k:report[k] for k in ('status','actor_generations','observed_measurements_reused','source_edit_counts','new_activity')},ensure_ascii=False))


if __name__=='__main__':
    main()
