"""Byte-preserving archival of the two explicitly named trial runs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[2]
RUNS=('sdk-preflight-v01','measured-v01','failure-replay-v01')

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def archive(run):
    if run not in RUNS:raise ValueError('Unknown run')
    source=ROOT/'tmp/basis-trial-stopped-update-replay-v01' if run=='failure-replay-v01' else ROOT/'runs/basis-trial'/run
    target=ROOT/'artifacts/basis-trial/2026-10-22'/run
    target.mkdir(parents=True,exist_ok=False)
    records={}
    for path in sorted(source.rglob('*')):
        if path.is_symlink():raise ValueError('Symlink in run')
        if not path.is_file():continue
        rel=path.relative_to(source).as_posix();dest=target/'raw'/rel
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
        records['raw/'+rel]=dict(source=path.relative_to(ROOT).as_posix(),sha256=digest(path),bytes=path.stat().st_size)
    manifest=dict(version='basis-trial-archive-v0.1',run=run,evidence_kind='observed' if run=='measured-v01' else 'synthetic',
        files=records,raw_files=len(records),total_bytes=sum(v['bytes'] for v in records.values()))
    (target/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return verify(run)

def verify(run):
    target=ROOT/'artifacts/basis-trial/2026-10-22'/run
    manifest=json.loads((target/'manifest.json').read_bytes())
    actual={p.relative_to(target).as_posix() for p in (target/'raw').rglob('*') if p.is_file()}
    if actual!=set(manifest['files']):raise ValueError('Archive file membership mismatch')
    for rel,ref in manifest['files'].items():
        for path in [target/rel,ROOT/ref['source']]:
            if path.is_symlink() or not path.resolve().is_relative_to(ROOT) or digest(path)!=ref['sha256'] or path.stat().st_size!=ref['bytes']:
                raise ValueError('Archive/source bytes differ')
    return dict(status='passed',run=run,raw_files=len(actual),total_files=len(actual)+1,total_bytes=manifest['total_bytes'],
                manifest_sha256=digest(target/'manifest.json'),source_and_archive_equal=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['create','verify']);args=parser.parse_args()
    print(json.dumps([(archive if args.mode=='create' else verify)(name) for name in RUNS]))
