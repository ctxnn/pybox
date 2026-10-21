"""Verify the durable raw archive without relying on the original temp files."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda:file.read(1048576),b''):value.update(chunk)
    return value.hexdigest()


def verify(root):
    raw=root/'raw'
    report=json.loads((root/'archive-report.json').read_text())
    hashes=json.loads((root/'raw-sha256.json').read_text())
    for name,expected in hashes.items():
        path=raw/name
        assert not path.is_symlink() and path.resolve().is_relative_to(raw.resolve())
        assert path.is_file() and digest(path)==expected,'Archive mismatch: '+name
    count=0
    for manifest in report['original_manifests']:
        path=raw/manifest['path'];data=json.loads(path.read_text())
        if path.name=='evidence-sha256.json':base=path.parent
        else:
            milestone,attempt=path.name.removeprefix('pybox-').removesuffix('-sha256.json').split('-attempt-')
            choices=[p for p in raw.iterdir() if p.is_dir() and p.name.startswith('pybox-'+milestone+'-') and p.name.endswith('-'+attempt)]
            assert len(choices)==1; base=choices[0]
        for name,expected in data.items():
            candidate=Path(name)
            if candidate.is_absolute():
                original=str(candidate)
                if original.startswith('/tmp/'):original='/private'+original
                candidate=raw/Path(original).relative_to('/private/tmp')
            else:candidate=base/candidate
            assert candidate.resolve().is_relative_to(raw.resolve())
            assert digest(candidate)==expected,'Original manifest mismatch: '+str(path)+' -> '+name
            count+=1
    return dict(passed=True,files=len(hashes),original_manifests=len(report['original_manifests']),original_manifest_entries=count)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]/'evidence')
    args=parser.parse_args();print(json.dumps(verify(args.root),indent=2))
