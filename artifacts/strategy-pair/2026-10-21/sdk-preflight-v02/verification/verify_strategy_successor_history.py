from pathlib import Path
import hashlib, json, subprocess, sys
root=Path.cwd();sys.path.insert(0,str(root))
from rsi_eval.strategy_pair_preparation import canonical,verify_prior_inputs
sha=lambda raw:hashlib.sha256(raw).hexdigest()
archives={
 'artifacts/strategy-pair/2026-10-21/v02':'fcddf54d8a29404ea3dee64d4298c46df62eb087720b7ae4b45ee654bda03a73',
 'artifacts/strategy-measured/2026-10-21/v01':'666e78f2b60e26f3dfc58095a4fc9d5ce8553208a2a5bbc963bc0cd7e952ab48'}
counts={}
for relative,digest in archives.items():
    base=root/relative
    assert sha((base/'manifest.json').read_bytes())==digest
    manifest=json.loads((base/'manifest.json').read_bytes())
    assert {p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file()}==set(manifest['files'])|{'manifest.json'}
    for name,value in manifest['files'].items():assert sha((base/name).read_bytes())==value,name
    counts[relative]=len(manifest['files'])+1
base=root/'artifacts/strategy-measured/2026-10-21/v01'
manifest=json.loads((base/'manifest.json').read_bytes())
sources={k:v for k,v in manifest['source_map'].items() if k.startswith('runs/')}
assert len(sources)==33
for source,target in sources.items():assert (root/source).read_bytes()==(base/target).read_bytes(),source
frozen=json.loads((base/'raw/preparation/runtime-freeze.json').read_bytes())['files']
revision='15144dc0fad8aee0ceae77535563fb6fc1b22144'
names=list(frozen)
raw=subprocess.check_output(['git','cat-file','--batch'],input=''.join(revision+':'+name+'\n' for name in names).encode())
cursor=0
for name in names:
    end=raw.index(b'\n',cursor)
    header=raw[cursor:end].split();assert header[1]==b'blob',name
    length=int(header[2]);cursor=end+1
    assert sha(raw[cursor:cursor+length])==frozen[name],name
    cursor+=length+1
assert cursor==len(raw)
report=dict(status='passed',archives=counts,old_measured_raw_files_unchanged=33,
            historical_runtime_commit=revision,historical_runtime_files_verified=len(frozen),
            prior_inputs=verify_prior_inputs(root),research_activity=dict(model_requests=0,task_executions=0))
(root/'tmp/strategy-successor-history.json').write_bytes(canonical(report)+b'\n')
print(json.dumps(report,ensure_ascii=False))
