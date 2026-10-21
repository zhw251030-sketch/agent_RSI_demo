"""Verify offline analysis, literal annotations and frozen sources without execution."""
import argparse
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest

from audit import analyze, canonical, sha


def verify(root):
    root=Path(root).resolve()
    base=root/'analysis/strategy-v03'
    suite=unittest.defaultTestLoader.discover(str(base),pattern='test_audit.py')
    result=unittest.TextTestRunner(stream=io.StringIO()).run(suite)
    assert result.testsRun==15 and result.wasSuccessful() and not result.skipped
    read=lambda path: json.loads(path.read_bytes())
    computed=analyze(root)
    assert computed==read(base/'results.json'),'Descriptive analysis differs'
    actors={r['slot_id']:r for r in computed['actors']}
    claims=read(base/'edit-claims.json')
    assert len(claims['records'])==32 and {r['slot_id'] for r in claims['records']}==set(actors)
    inputs={}

    def check_file(name,digest):
        path=root/name
        assert path.resolve().is_relative_to(root) and not path.is_symlink()
        assert sha(path.read_bytes())==digest,name
        if name in inputs:
            assert inputs[name]==digest
        inputs[name]=digest

    for name,digest in claims['input_file_sha256'].items():
        check_file(name,digest)
    for rec in claims['records']:
        actor=actors[rec['slot_id']]
        check_file(rec['claim_file'],rec['claim_file_sha256'])
        literal=read(root/rec['claim_file'])['explanation']
        assert literal==actor['explanation']==rec['explanation_full']
        assert literal[rec['quote_start_character']:rec['quote_end_character_exclusive']]==rec['quote']
        assert rec['classification'] in ('supported','contradicted','unknown','no_specific_claim')
        for role in ('parent','child'):
            check_file(rec['source_paths'][role],rec['source_sha256'][role])
        assert rec['source_sha256']['child']==actor['source_sha256']
        assert rec['source_sha256']['parent']==actor['parent_source']['source_sha256']
        for evidence in rec['evidence']:
            check_file(evidence['path'],evidence['sha256'])
            lines=(root/evidence['path']).read_text(encoding='utf-8').splitlines()
            assert '\n'.join(lines[evidence['line_start']-1:evidence['line_end']])==evidence['excerpt'].replace('\\n','\n')
    counts=dict(sorted(Counter(r['classification'] for r in claims['records']).items()))
    assert counts==claims['classification_counts']
    symbolic=read(base/'symbolic-structure.json')
    for name,digest in symbolic['evidence_sha256'].items():
        check_file(name,digest)
    symbolic_actors=[r for r in symbolic['rows'] if r['id'] in actors]
    assert len(symbolic_actors)==16
    for rec in symbolic_actors:
        actor=actors[rec['id']]
        assert (rec['source_sha256'],rec['declared_n_params'],rec['nmse'])==(actor['source_sha256'],actor['n_params'],actor['nmse'])
    sys.path.insert(0,str(root))
    from rsi_eval.strategy_pair_preparation import assert_runtime
    freeze=read(root/'artifacts/strategy-measured/2026-10-21/v03/raw/preparation/runtime-freeze.json')['files']
    assert_runtime(root,freeze)
    for name,digest in inputs.items():
        check_file(name,digest)
    names=['audit.py','test_audit.py','verify.py','results.json','edit-claims.json','edit-claims.md',
           'symbolic-structure.json','symbolic-structure.md','variation-design.json','variation-design.md']
    report=dict(status='passed',actor_population=32,symbolic_submissions=16,old_measurements_reused=716,
                tests=dict(run=result.testsRun,passed=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped)),
                annotation_counts=counts,annotation_file_bindings_verified=len(inputs),
                annotation_verification_scope='Exact quotes, source hashes, excerpts and coverage; human semantic labels are not automatically proved.',
                frozen_runtime_files_unchanged=len(freeze),raw_archive_files_verified=computed['archive_files_verified'],
                same_input_group_sizes=sorted(g['n_generations'] for g in computed['groups']),
                files_sha256={str((base/n).relative_to(root)).replace('\\','/'):sha((base/n).read_bytes()) for n in names},
                activity=computed['new_activity'])
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    output=(root/args.output).resolve()
    if not output.is_relative_to(root/'tmp'):
        raise ValueError('Verification output must be under tmp')
    result=verify(root)
    with output.open('xb') as stream:
        stream.write(canonical(result)+b'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='files_sha256'},ensure_ascii=False))


if __name__=='__main__':
    main()
