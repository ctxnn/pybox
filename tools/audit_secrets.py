"""Offline artifact/Git credential scan. Output metadata only, never matched values."""
import argparse
import base64
import datetime
import json
from pathlib import Path
import re
import subprocess

RULES={
    'nvidia_api_key':rb'nvapi-[A-Za-z0-9_-]{32,}',
    'openai_anthropic_router_key':rb'sk-(?:proj-|or-v1-|ant-api[0-9]+-)?[A-Za-z0-9_-]{32,}',
    'github_token':rb'(?:gh[pousr]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{30,})',
    'google_api_key':rb'AIza[0-9A-Za-z_-]{30,}',
    'slack_token':rb'xox[baprs]-[A-Za-z0-9-]{20,}',
    'aws_access_key_id':rb'(?:AKIA|ASIA)[A-Z0-9]{16}',
    'private_key_pem':rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
    'literal_bearer_token':rb'Bearer[ \t]+[A-Za-z0-9_./+-]{32,}',
}
LITERAL=re.compile(rb'''(?i)(?:api[_-]?key|access[_-]?token|secret[_-]?key)\s*["']?\s*[:=]\s*["']([^"'\r\n]{20,256})["']''')
PLACEHOLDERS=(b'controlled',b'example',b'placeholder',b'dummy',b'redacted',b'test',b'getenv',b'getpass',b'environ',b'$')


def inspect_bytes(data):
    results=[]
    views=[('raw',data)]
    if b'\\u00' in data:
        views.append(('json_escape',re.sub(rb'\\u00([0-9a-fA-F]{2})',lambda m:bytes([int(m[1],16)]),data)))
    for encoding,view in views:
        for name,pattern in RULES.items():
            matches=list(re.finditer(pattern,view))
            if matches:results.append(dict(rule=name,encoding=encoding,count=len(matches)))
        candidates=[]
        for match in LITERAL.finditer(view):
            value=match[1]
            if any(x in value.lower() for x in PLACEHOLDERS) or len(set(value))<12:continue
            if re.fullmatch(rb'[A-Za-z0-9_./+=-]+',value):candidates.append(match)
        if candidates:results.append(dict(rule='suspicious_literal_key_assignment',encoding=encoding,count=len(candidates)))
    # Detect standard base64-encoded provider-key strings without printing/retaining them.
    encoded=0
    for match in re.finditer(rb'(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,4096}={0,2}(?![A-Za-z0-9+/])',data):
        try:decoded=base64.b64decode(match[0]+b'='*((-len(match[0]))%4),validate=True)
        except ValueError:continue
        if any(re.search(pattern,decoded) for pattern in RULES.values()):encoded+=1
    if encoded:results.append(dict(rule='base64_encoded_credential',encoding='base64',count=encoded))
    return results


def scan_paths(roots):
    seen=set();hits=[];count=total=0;errors=[];links=[]
    for root in roots:
        if not root.exists():errors.append(dict(path=str(root),error='missing'));continue
        for path in ([root] if root.is_file() else root.rglob('*')):
            if path.is_symlink():links.append(str(path));continue
            if not path.is_file():continue
            identity=path.stat();identity=(identity.st_dev,identity.st_ino)
            if identity in seen:continue
            seen.add(identity)
            try:data=path.read_bytes()
            except OSError as exc:errors.append(dict(path=str(path),error=type(exc).__name__));continue
            count+=1;total+=len(data)
            found=inspect_bytes(data)
            if found:hits.append(dict(path=str(path),findings=found))
    return dict(files=count,bytes=total,findings=hits,errors=errors,symlinks_not_followed=links)


def scan_git(repo):
    inventory=subprocess.check_output(['git','cat-file','--batch-all-objects','--batch-check=%(objectname) %(objecttype) %(objectsize)'],cwd=repo,text=True)
    found=[];count=total=0
    for line in inventory.splitlines():
        oid,kind,size=line.split()
        if kind not in ('blob','commit','tag'):continue
        data=subprocess.check_output(['git','cat-file',kind,oid],cwd=repo)
        assert len(data)==int(size)
        count+=1;total+=len(data);matches=inspect_bytes(data)
        if matches:found.append(dict(object=oid,type=kind,findings=matches))
    return dict(objects=count,bytes=total,findings=found,scope='All stored blob/commit/tag objects, including unreachable objects')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--external-session-log',type=Path)
    args=parser.parse_args();repo=args.repo
    roots=[repo,*sorted(Path('/private/tmp').glob('pybox-*'))]
    legacy=Path.home()/'.capy/work'
    if legacy.exists():roots.extend(sorted(legacy.glob('pybox*')))
    runtime=Path.home()/'.pybox/runtime'
    if runtime.exists():roots.extend(p for p in runtime.rglob('*') if p.is_file() and (p.suffix=='.log' or p.name.endswith('.log.json')))
    report=dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),roots=[str(p) for p in roots],
                artifacts=scan_paths(roots),git=scan_git(repo),
                methods=['Provider-key prefixes','Literal credential assignments and bearer tokens','Private-key PEM','JSON-escaped and base64 variants','All stored Git blob/commit/tag objects'],
                limits='Pattern-based detection does not prove absence of arbitrary unknown/obfuscated secrets; external services and unrelated app logs are outside artifact scope.')
    if args.external_session_log:
        report['separate_app_session_log']=scan_paths([args.external_session_log])
    report['project_artifacts_clean']=not(report['artifacts']['findings'] or report['artifacts']['errors'] or report['git']['findings'])
    # Positive controls are created only in memory, never written as key strings.
    positive=b'nvapi-'+b'X'*64
    report['scanner_positive_controls']=bool(inspect_bytes(positive) and inspect_bytes(base64.b64encode(positive)))
    assert report['scanner_positive_controls']
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('project_artifacts_clean','scanner_positive_controls')},indent=2))
    for scope in ('artifacts','git','separate_app_session_log'):
        if scope in report:
            result=report[scope];print(scope,json.dumps({k:v for k,v in result.items() if k!='symlinks_not_followed'}))


if __name__=='__main__':main()
