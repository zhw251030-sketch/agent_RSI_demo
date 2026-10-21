from pathlib import Path
import hashlib,json,subprocess,sys
root=Path.cwd();sys.path.insert(0,str(root))
from rsi_eval.strategy_pair_preparation import canonical,verify_prior_inputs
sha=lambda raw:hashlib.sha256(raw).hexdigest()
anchors={
 'artifacts/strategy-pair/2026-10-21/v02':'fcddf54d8a29404ea3dee64d4298c46df62eb087720b7ae4b45ee654bda03a73',
 'artifacts/strategy-measured/2026-10-21/v01':'666e78f2b60e26f3dfc58095a4fc9d5ce8553208a2a5bbc963bc0cd7e952ab48',
 'artifacts/strategy-pair/2026-10-21/sdk-preflight-v02':'d243c9089e2bf37235b8c72fa7d3bcc2c275365393686cb448163070d06601cc',
 'artifacts/strategy-measured/2026-10-21/v02':'f1adac030d1bf1efb60e534f387b737407b0df67ac742d9b7637930fbc12ef61'}
counts={}; originals={}; historical={}
for relative,expected in anchors.items():
 base=root/relative; raw=(base/'manifest.json').read_bytes();assert sha(raw)==expected,relative
 m=json.loads(raw); assert {p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file()}==set(m['files'])|{'manifest.json'}
 for name,h in m['files'].items():assert sha((base/name).read_bytes())==h,(relative,name)
 counts[relative]=len(m['files'])+1
 originals[relative]=0
 for source,target in m['source_map'].items():
  if source.startswith('runs/'):
   assert (root/source).read_bytes()==(base/target).read_bytes(),source
   originals[relative]+=1
for relative,revision in [('artifacts/strategy-measured/2026-10-21/v01','15144dc0fad8aee0ceae77535563fb6fc1b22144'),('artifacts/strategy-measured/2026-10-21/v02','729318e817cda5ea581fdb033201ce0aeab4dbdb')]:
 frozen=json.loads((root/relative/'raw/preparation/runtime-freeze.json').read_bytes())['files']
 names=list(frozen);raw=subprocess.check_output(['git','cat-file','--batch'],input=''.join(revision+':'+n+'\n' for n in names).encode())
 cursor=0
 for name in names:
  end=raw.index(b'\n',cursor);header=raw[cursor:end].split();assert header[1]==b'blob',name
  length=int(header[2]);cursor=end+1;assert sha(raw[cursor:cursor+length])==frozen[name],name;cursor+=length+1
 assert cursor==len(raw)
 historical[revision]=len(frozen)
report=dict(status='passed',archives=counts,original_run_files_unchanged=originals,historical_runtime_commits=historical,prior_inputs=verify_prior_inputs(root),research_activity=dict(model_requests=0,task_executions=0))
(root/'tmp/strategy-v03-history.json').write_bytes(canonical(report)+b'\n')
print(json.dumps(report,ensure_ascii=False))
