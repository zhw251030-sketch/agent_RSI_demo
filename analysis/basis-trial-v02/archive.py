"""Byte-preserving archival of the two explicitly named successor trial runs.

This tool copies existing run evidence only. It never invokes the controller,
model provider, executor, or scoring code. Source paths retain their original
run identity; synthetic rehearsals cannot be relabeled as observed outcomes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
RUNS = ('sdk-preflight-v01', 'measured-v01')
VERSION = 'basis-trial-archive-v0.2'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _locations(run):
    if run not in RUNS:
        raise ValueError('Unknown successor run')
    source = ROOT / 'runs/basis-trial-v02' / run
    target = ROOT / 'artifacts/basis-trial-v02/2026-10-22' / run
    return source, target


def _contained(path):
    if not path.resolve().is_relative_to(ROOT):
        raise ValueError('Archive path outside repository')
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or (hasattr(ancestor, 'is_junction') and ancestor.is_junction()):
            raise ValueError('Linked archive or run path')
        if ancestor == ROOT:
            break


def _files(directory):
    _contained(directory)
    if not directory.is_dir():
        raise ValueError('Expected an existing evidence directory')
    records = {}
    for path in sorted(directory.rglob('*')):
        _contained(path)
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError('Unexpected evidence entry')
        records[path.relative_to(directory).as_posix()] = path
    if not records:
        raise ValueError('Empty evidence directory')
    return records


def archive(run):
    source, target = _locations(run)
    sources = _files(source)
    _contained(target)
    target.mkdir(parents=True, exist_ok=False)
    records = {}
    for rel, path in sources.items():
        destination = target / 'raw' / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        records['raw/' + rel] = {
            'source': path.relative_to(ROOT).as_posix(),
            'sha256': digest(path),
            'bytes': path.stat().st_size,
        }
    manifest = {
        'version': VERSION,
        'run': run,
        'evidence_kind': 'observed' if run == 'measured-v01' else 'synthetic',
        'files': records,
        'raw_files': len(records),
        'total_bytes': sum(item['bytes'] for item in records.values()),
    }
    with (target / 'manifest.json').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return verify(run)


def verify(run):
    source, target = _locations(run)
    _contained(target / 'manifest.json')
    manifest = json.loads((target / 'manifest.json').read_bytes())
    expected_fields = {'version', 'run', 'evidence_kind', 'files', 'raw_files', 'total_bytes'}
    if (type(manifest) is not dict or set(manifest) != expected_fields
            or manifest['version'] != VERSION or manifest['run'] != run
            or manifest['evidence_kind'] != ('observed' if run == 'measured-v01' else 'synthetic')
            or type(manifest['files']) is not dict):
        raise ValueError('Archive identity or evidence kind mismatch')
    sources = _files(source)
    archived = _files(target / 'raw')
    expected = {'raw/' + rel for rel in sources}
    if (set(archived) != set(sources) or set(manifest['files']) != expected
            or type(manifest['raw_files']) is not int or manifest['raw_files'] != len(expected)):
        raise ValueError('Archive/source file membership mismatch')
    total_bytes = 0
    for rel, source_path in sources.items():
        item = manifest['files']['raw/' + rel]
        if (type(item) is not dict or set(item) != {'source', 'sha256', 'bytes'}
                or item['source'] != source_path.relative_to(ROOT).as_posix()
                or type(item['bytes']) is not int or item['bytes'] < 0):
            raise ValueError('Original source identity or file size mismatch')
        for path in (source_path, archived[rel]):
            if digest(path) != item['sha256'] or path.stat().st_size != item['bytes']:
                raise ValueError('Archive/source bytes differ')
        total_bytes += item['bytes']
    if type(manifest['total_bytes']) is not int or manifest['total_bytes'] != total_bytes:
        raise ValueError('Archive total bytes mismatch')
    return {
        'status': 'passed', 'run': run, 'evidence_kind': manifest['evidence_kind'],
        'raw_files': len(expected), 'total_files': len(expected) + 1,
        'total_bytes': total_bytes, 'manifest_sha256': digest(target / 'manifest.json'),
        'source_and_archive_equal': True,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['create', 'verify'])
    parser.add_argument('--run', choices=RUNS)
    args = parser.parse_args()
    action = archive if args.mode == 'create' else verify
    print(json.dumps([action(name) for name in ([args.run] if args.run else RUNS)]))
