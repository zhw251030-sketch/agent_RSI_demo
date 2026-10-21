"""Additive freeze for the bounded strategy runner; no SDK, secrets or execution."""
import hashlib
import json
from pathlib import Path
import platform
import subprocess

from .strategy_partition import safe_path
from .strategy_binding import FUTURE_ALLOCATION, FUTURE_ALLOCATION_SHA256

PRIOR_ARCHIVE = 'artifacts/strategy-interface/2026-10-21/v01'
PRIOR_MANIFEST_SHA256 = 'd9387df4aa3366dc9e054e39f5235ff2cd86cb7aa5626e2aef1f072256cad15b'
PROTOCOL = 'docs/protocols/2026-10-21-strategy-pair-v0.2.md'
VERSION = 'strategy-pair-preparation-v0.1'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    path = Path(path)
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in (path, *path.parents)):
        raise ValueError('Symlinked output')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(canonical(value)+b'\n')
        stream.flush()
        __import__('os').fsync(stream.fileno())
    return sha(path.read_bytes())


def verify_prior_inputs(root):
    root=Path(root).resolve()
    archive=safe_path(root,PRIOR_ARCHIVE)
    raw=(archive/'manifest.json').read_bytes()
    if sha(raw)!=PRIOR_MANIFEST_SHA256:
        raise ValueError('Prior archive manifest hash changed')
    manifest=json.loads(raw)
    for name,digest in manifest['files'].items():
        if sha(safe_path(archive,name).read_bytes())!=digest:
            raise ValueError('Prior archive hash changed: '+name)
    preparation=read(archive/'preparation/preparation.json')
    for name,digest in preparation['runtime_files_sha256'].items():
        if sha(safe_path(root,name).read_bytes())!=digest:
            raise ValueError('Frozen legacy runtime changed: '+name)
    package=read(archive/'preparation/learning-package.json')
    for name,digest in package['provenance']['source_files'].items():
        if sha(safe_path(root,name).read_bytes())!=digest:
            raise ValueError('Pinned learning input hash changed: '+name)
    raw_count=0
    for relative in ('artifacts/decision-replay/2026-10-21/v01',
                     'artifacts/edit-commitment/2026-10-21/v01',
                     'artifacts/state-generation/2026-10-21/v01',
                     'artifacts/state-generation/2026-10-21/v02'):
        old=safe_path(root,relative)
        body=read(old/'manifest.json')
        files=body.get('raw_files',body.get('files'))
        for name,digest in files.items():
            if sha(safe_path(old,name).read_bytes())!=digest:
                raise ValueError('Old raw archive hash changed: '+relative+'/'+name)
        raw_count+=len(files)
    if sha(safe_path(root,FUTURE_ALLOCATION).read_bytes())!=FUTURE_ALLOCATION_SHA256:
        raise ValueError('Future allocation changed')
    return dict(old_runtime_files=len(preparation['runtime_files_sha256']),old_raw_files=raw_count,
        learning_transitions=sum(package['provenance']['cohort_counts'].values()),
        update_packet_bytes=preparation['update_packet_bytes'],
        prior_manifest_sha256=PRIOR_MANIFEST_SHA256)


def model_settings(root):
    from scripts.run_checked_feedback import _model_configuration
    digest,public,effective=_model_configuration(Path(root)/'configs/models/minimax-m3.json',{'max_output_tokens':8192})
    effective['timeout']=180
    return dict(source_sha256=digest,public=public,effective=effective)


def runtime_files(root):
    from scripts.prepare_strategy_pair import _runtime
    return _runtime(root)


def assert_runtime(root, frozen):
    for name,digest in frozen.items():
        if sha(safe_path(root,name).read_bytes())!=digest:
            raise ValueError('Frozen current runtime hash changed: '+name)
    if runtime_files(root)!=frozen:
        raise ValueError('Current runtime file inventory changed')


def prepare(root, output, *, allow_dirty=False):
    root=Path(root).resolve();output=Path(output).resolve()
    if not output.is_relative_to(root):
        raise ValueError('Output must be inside project')
    safe_path(root,output.relative_to(root).as_posix())
    if output.exists():
        raise FileExistsError('Preparation output exists')
    if platform.python_version()!='3.12.14':
        raise ValueError('Requires frozen Python3.12.14')
    dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=root).strip())
    if dirty and not allow_dirty:
        raise ValueError('Clean implementation commit required')
    old=verify_prior_inputs(root)
    runtime=runtime_files(root)
    prior=root/PRIOR_ARCHIVE/'preparation'
    payloads={name:read(prior/name) for name in ('learning-package.json','update-packet.json','future-allocation.json')}
    payloads['settings.json']=model_settings(root)
    payloads['runtime-freeze.json']=dict(version=VERSION,
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
        checkout_clean=not dirty,files=runtime,sha256=sha(canonical(runtime)))
    payloads['preparation.json']=dict(version=VERSION,execution_ready=False,
        protocol=PROTOCOL,prior_inputs=old,requires='Complete actual-SDK synthetic36 audit before a separate real run.',
        research_activity=dict(model_requests=0,candidate_executions=0,task_evaluations=0,strategy_updates=0))
    output.mkdir(parents=True,exist_ok=False)
    files={name:write(output/name,value) for name,value in payloads.items()}
    write(output/'manifest.json',dict(version=VERSION,files=files))
    return verify(root,output)


def verify(root, output):
    root=Path(root).resolve();output=Path(output).resolve()
    manifest=read(output/'manifest.json')
    required={'learning-package.json','update-packet.json','future-allocation.json','settings.json','runtime-freeze.json','preparation.json'}
    if set(manifest)!={'version','files'} or manifest.get('version')!=VERSION or set(manifest['files'])!=required:
        raise ValueError('Preparation version differs')
    if {p.name for p in output.iterdir()}!=set(manifest['files'])|{'manifest.json'}:
        raise ValueError('Preparation files differ')
    for name,digest in manifest['files'].items():
        if sha(safe_path(output,name).read_bytes())!=digest:
            raise ValueError('Preparation hash mismatch')
    frozen=read(output/'runtime-freeze.json')
    if sha(canonical(frozen['files']))!=frozen['sha256']:
        raise ValueError('Runtime inventory hash mismatch')
    assert_runtime(root,frozen['files'])
    old=verify_prior_inputs(root)
    for name in ('learning-package.json','update-packet.json','future-allocation.json'):
        if read(output/name)!=read(root/PRIOR_ARCHIVE/'preparation'/name):
            raise ValueError('Preparation differs from pinned prior input: '+name)
    info=read(output/'preparation.json')
    if info['prior_inputs']!=old or read(output/'settings.json')!=model_settings(root):
        raise ValueError('Preparation source/settings differ')
    return dict(version=VERSION,status='passed',execution_ready=False,
        manifest_sha256=sha((output/'manifest.json').read_bytes()),runtime_sha256=frozen['sha256'],
        runtime_files=len(frozen['files']),old_runtime_files=old['old_runtime_files'],old_raw_files=old['old_raw_files'],
        update_packet_bytes=old['update_packet_bytes'],research_activity=info['research_activity'])
