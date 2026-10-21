from pathlib import Path,PurePosixPath
import hashlib,json,sys,tarfile
root=Path.cwd();run_id=sys.argv[1]
assert run_id in ('sdk-preflight-v03','measured-v03')
export=json.loads((root/('tmp/strategy-'+run_id+'-export.json')).read_bytes())
archive=root/('tmp/strategy-'+run_id+'.tar.gz')
sha=lambda raw:hashlib.sha256(raw).hexdigest()
assert sha(archive.read_bytes())==export['archive_sha256']
with tarfile.open(archive,'r:gz') as stream:
    members=stream.getmembers();assert len(members)==len(export['files'])
    assert {m.name for m in members}==set(export['files'])
    for member in members:
        parts=PurePosixPath(member.name)
        assert member.isfile() and not parts.is_absolute() and '..' not in parts.parts
        assert member.name.startswith('runs/strategy-pair/'+run_id+'/') or (run_id=='measured-v03' and member.name.startswith('runs/role_executor_feedback/'))
        path=root/member.name;assert path.resolve().is_relative_to(root.resolve())
        data=stream.extractfile(member).read();assert sha(data)==export['files'][member.name]
        if path.exists():assert path.read_bytes()==data
        else:
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as target:target.write(data)
assert all(sha((root/name).read_bytes())==digest for name,digest in export['files'].items())
print(json.dumps(dict(status='imported_and_hash_verified',run_id=run_id,files=len(export['files']))))
