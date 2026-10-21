from pathlib import Path
import hashlib,json,sys,tarfile
root=Path.cwd();run_id=sys.argv[1]
assert run_id in ('sdk-preflight-v03','measured-v03')
run=root/'runs/strategy-pair'/run_id
assert (run/'result.json').is_file()
files={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
       for p in sorted(run.rglob('*')) if p.is_file() and not p.is_symlink()}
extra=[]
unbound=[]
if run_id=='measured-v03':
    start=json.loads((root/'tmp/strategy-measured-v03-start.json').read_bytes())
    before=set(start['role_execution_directories'])
    base=root/'runs/role_executor_feedback'
    extra=[p for p in sorted(base.iterdir()) if p.is_dir() and p.name not in before]
    for directory in extra:
        for p in sorted(directory.rglob('*')):
            assert not p.is_symlink()
            if p.is_file():files[p.relative_to(root).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    report=json.loads((run/'experiment/summary.json').read_bytes())
    receipts={event['receipt']['path'] for event in report['events'] if event['kind']=='measurement_recorded'}
    assert receipts<=set(files)
    receipt_directories=set()
    for name in receipts:
        path=Path(name)
        assert path.parts[:2]==('runs','role_executor_feedback'),name
        receipt_directories.add(path.parts[2])
    new_directories={p.name for p in extra}
    assert receipt_directories<=new_directories
    unbound=sorted(new_directories-receipt_directories)
archive=root/('tmp/strategy-'+run_id+'.tar.gz')
with tarfile.open(archive,'w:gz') as stream:
    for name in files:stream.add(root/name,arcname=name,recursive=False)
report=dict(run_id=run_id,files=files,file_count=len(files),role_execution_directories=len(extra),
            unbound_role_execution_directories=unbound,
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),archive_bytes=archive.stat().st_size)
(root/('tmp/strategy-'+run_id+'-export.json')).write_bytes(json.dumps(report,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()+b'\n')
print(json.dumps({k:v for k,v in report.items() if k!='files'}))
