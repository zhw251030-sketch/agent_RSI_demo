"""Fetch pinned public source archives and materialize audited task inputs.

No model calls. vendor/ contains reference solutions: it is NOT agent context.
Existing files with mismatching bytes are never silently replaced.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def local_path(relative):
    path = ROOT / relative
    if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
        raise ValueError('Unsafe local destination')
    return path


def check(path, expected_hash, expected_size=None):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected a regular file: ' + str(path.relative_to(ROOT)))
    if expected_size is not None and path.stat().st_size != expected_size:
        raise ValueError('File size mismatch: ' + path.name)
    if sha256(path) != expected_hash:
        raise ValueError('SHA256 mismatch: ' + path.name)


def source(spec):
    archive = local_path('tmp/downloads/' + spec['name'] + '-' + spec['commit'] + '.zip')
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        partial = archive.with_suffix('.part')
        req = urllib.request.Request(spec['url'], headers={'User-Agent': 'agent-RSI-data-preparation/0.1'})
        with urllib.request.urlopen(req, timeout=90) as response, partial.open('wb') as output:
            shutil.copyfileobj(response, output)
        check(partial, spec['sha256'], spec['size'])
        partial.replace(archive)
    check(archive, spec['sha256'], spec['size'])
    target = local_path('vendor/' + spec['name'])
    target.parent.mkdir(parents=True, exist_ok=True)
    marker_name = '.acquisition.json'
    with zipfile.ZipFile(archive) as zf:
        members = []
        top = None
        for info in zf.infolist():
            p = PurePosixPath(info.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in info.filename:
                raise ValueError('Unsafe archive path')
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError('Archive symlinks are unsupported')
            if top is None:
                top = p.parts[0]
            if p.parts[0] != top:
                raise ValueError('Archive must have a single root')
            if not info.is_dir():
                members.append((info, Path(*p.parts[1:])))
        if target.exists():
            marker = json.loads((target / marker_name).read_text())
            if marker['commit'] != spec['commit'] or marker['sha256'] != spec['sha256']:
                raise ValueError('Existing source version mismatch')
            for info, rel in members:
                path = target / rel
                if path.is_symlink() or not path.is_file() or sha256(path) != hashlib.sha256(zf.read(info)).hexdigest():
                    raise ValueError('Existing source file mismatch: ' + str(rel))
        else:
            with tempfile.TemporaryDirectory(prefix='extract-', dir=target.parent) as td:
                stage = Path(td) / 'tree'
                stage.mkdir()
                for info, rel in members:
                    out = stage / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(zf.read(info))
                    mode = info.external_attr >> 16
                    if mode & 0o111:
                        out.chmod(0o755)
                (stage / marker_name).write_text(json.dumps(spec, indent=2) + '\n')
                stage.rename(target)
    return {'name': spec['name'], 'commit': spec['commit'], 'archive_sha256': spec['sha256'],
            'archive_bytes': archive.stat().st_size, 'source_files_verified': len(members)}


def materialize(source_root, source_path, target, expected_hash):
    original = source_root / source_path
    check(original, expected_hash)
    if target.exists():
        check(target, expected_hash)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
        check(target, expected_hash)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='configs/tasks/downloads-v0.1.json')
    args = parser.parse_args()
    config = json.loads(local_path(args.config).read_text())
    report = {'schema_version': '0.1', 'model_calls': 0, 'sources': []}
    for spec in config['sources']:
        report['sources'].append(source(spec))
    cfg = config['planning']
    manifest = json.loads(local_path(cfg['manifest']).read_text())
    entries = [manifest['domain']] + manifest['tasks']
    for entry in entries:
        rel = PurePosixPath(entry['upstream_path']).relative_to(cfg['source_prefix'])
        materialize(local_path('vendor/llm-genplan'), entry['upstream_path'],
                    local_path(cfg['data_dir'] + '/' + str(rel)), entry['sha256'])
    report['planning_files_verified'] = len(entries)
    if 'symbolic' in config:
        cfg = config['symbolic']
        for entry in cfg['files']:
            materialize(local_path('vendor/' + cfg['source_name']), entry['upstream_path'],
                        local_path(cfg['data_dir'] + '/' + entry['relative_path']), entry['sha256'])
        report['symbolic_files_verified'] = len(cfg['files'])
    output = local_path('runs/data-preparation/acquisition.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
