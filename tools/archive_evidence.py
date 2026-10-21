"""Copy a fixed inventory of PyBox temp artifacts and verify immutable bytes."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda:file.read(1048576),b''):value.update(chunk)
    return value.hexdigest()


def write_json(path,value):
    with path.open('x') as file:json.dump(value,file,indent=2);file.write('\n')


def archive(source,destination):
    os.umask(0o077)
    source=source.resolve();destination=destination.resolve()
    destination.mkdir(mode=0o700,parents=True,exist_ok=True)
    raw=destination/'raw';raw.mkdir(mode=0o700)
    originals=sorted(p for p in source.iterdir() if p.name.startswith('pybox-'))
    assert originals,'No PyBox artifacts found'
    entries=[];directories=[]
    for root in originals:
        if root.is_symlink():raise RuntimeError('Symlink requires explicit review: '+str(root))
        paths=[root]
        if root.is_dir():
            paths.extend(sorted(root.rglob('*')))
        for old in paths:
            metadata=old.lstat();relative=old.relative_to(source);new=raw/relative
            if stat.S_ISDIR(metadata.st_mode):
                new.mkdir(mode=0o700,exist_ok=True);directories.append(str(relative));continue
            if not stat.S_ISREG(metadata.st_mode):raise RuntimeError('Special file requires review: '+str(old))
            before=digest(old)
            shutil.copy2(old,new,follow_symlinks=False)
            assert digest(new)==before,'Copy hash mismatch: '+str(relative)
            after=old.stat()
            assert (after.st_size,after.st_mtime_ns)==(metadata.st_size,metadata.st_mtime_ns),'Source changed: '+str(old)
            assert digest(old)==before,'Source contents changed: '+str(old)
            entries.append(dict(path=str(relative),sha256=before,bytes=metadata.st_size,
                                original_mode=oct(stat.S_IMODE(metadata.st_mode)),original_mtime_ns=metadata.st_mtime_ns))
    original_manifests=[]
    for path in sorted(raw.rglob('*.json')):
        if not (path.name.endswith('-sha256.json') or path.name=='evidence-sha256.json'):continue
        data=json.loads(path.read_text())
        assert isinstance(data,dict) and all(isinstance(v,str) and re.fullmatch('[0-9a-f]{64}',v) for v in data.values())
        if path.name=='evidence-sha256.json':base=path.parent
        else:
            match=re.fullmatch(r'pybox-(.+)-attempt-(\d+)-sha256.json',path.name)
            assert match,path
            choices=[p for p in raw.iterdir() if p.is_dir() and p.name.startswith('pybox-'+match[1]+'-') and p.name.endswith('-'+match[2])]
            assert len(choices)==1,(path,choices)
            base=choices[0]
        for name,expected in data.items():
            old=Path(name)
            if old.is_absolute():
                if str(old).startswith('/tmp/'):old=Path('/private'+str(old))
                target=raw/old.relative_to(source)
            else:target=base/old
            assert target.resolve().is_relative_to(raw),'Manifest escaped archive'
            assert target.is_file() and digest(target)==expected,'Original manifest failed: '+str(path)+' -> '+name
        original_manifests.append(dict(path=str(path.relative_to(raw)),verified_files=len(data),passed=True))
    # Freeze the raw copies. Historical embedded paths remain part of their hashes.
    for entry in entries:(raw/entry['path']).chmod(0o400)
    for folder in sorted((p for p in raw.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):folder.chmod(0o500)
    raw.chmod(0o500)
    mapping={prefix+old.name:str(raw/old.name) for old in originals for prefix in ('/private/tmp/','/tmp/')}
    write_json(destination/'path-map.json',dict(version=1,paths=mapping,
        note='Resolve historical embedded temp paths using longest-prefix match; raw files are byte-preserved.'))
    write_json(destination/'raw-sha256.json',{x['path']:x['sha256'] for x in entries})
    report=dict(version=1,utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source=str(source),raw=str(raw),
                top_level_items=len(originals),files=len(entries),bytes=sum(x['bytes'] for x in entries),
                directories=directories,entries=entries,original_manifests=original_manifests,verified=True)
    write_json(destination/'archive-report.json',report)
    print(json.dumps({k:report[k] for k in ('top_level_items','files','bytes','verified')},indent=2))
    print('Original SHA manifests verified:',len(original_manifests),'entries:',sum(x['verified_files'] for x in original_manifests))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path('/private/tmp'))
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args();archive(args.source,args.destination)
