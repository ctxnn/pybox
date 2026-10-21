"""Explicit finite NVIDIA NIM comparison under the dedicated runtime gates."""
import argparse
from contextlib import nullcontext
from dataclasses import asdict
import getpass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import uuid

MAIN=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MAIN))
from pybox import container
from pybox.mcp_policy import project_record
from pybox.nim import NimProvider,MODEL,ENDPOINT
from pybox.repair import Budget,RepairController,Limits
from pybox.repair_cases import CASES
from tools.runtime_validation import Runtime,require,save,stamp


def execute(evidence,prior_attempt=None):
    # Prompt on an owned terminal; never write a key into argv, env, source or files.
    key=getpass.getpass('NVIDIA API key (not echoed): ')
    provider=NimProvider(key)
    runtime=Runtime(evidence,MAIN)
    prior_requests=prior_executions=0
    if prior_attempt:
        prior=json.loads((prior_attempt/'outcome.json').read_text())
        require(prior['passed'] is False and prior['vm']=='Stopped' and prior['model'] in ('z-ai/glm-5.3-flash',MODEL),'invalid prior attempt')
        prior_requests=prior['budget']['model_requests']+prior.get('retained_prior_reservations',{}).get('model_requests',0)
        prior_executions=prior['budget']['executions']+prior.get('retained_prior_reservations',{}).get('executions',0)
        require(prior_requests in (1,2) and prior_executions==prior_requests and prior['budget']['unconfirmed_or_halted'],'unexpected prior reservation')
        tls=json.loads((MAIN/'evidence/raw/pybox-m6-tls-preflight.json').read_text())
        require(tls['python-default']['error_type']=='SSLCertVerificationError' and tls['mac-system']['verification']=='passed','TLS correction not verified')
    budget=Budget(Limits(model_requests=16-prior_requests,executions=24-prior_executions),evidence/'budget.jsonl')
    outcome=dict(passed=False,started_at=stamp(),model=MODEL,endpoint=ENDPOINT,episodes=[],
        scope='M6 finite controller/real NIM comparison; four synthetic programs, two arms, max two revisions each',
        provider_authorization='User authorized selecting another free NIM model after GLM failures; same supplied key; no OpenRouter',
        cost=dict(reported_cost_usd=None,reason='NVIDIA lists a free trial endpoint; settled bill/credits unavailable'),
        caps=dict(model_requests=16,max_tokens_per_request=2048,reserved_completion_tokens=32768,executions=24,
                  prompt_bytes_per_request=24576,concurrency=1,http_retries=0,admission_window_s=900))
    ca=Path('/etc/ssl/cert.pem');ca_stat=ca.stat()
    require(ca_stat.st_uid==0 and not ca_stat.st_mode&0o022,'system CA bundle is not trusted')
    outcome['tls']=dict(cafile=str(ca),sha256=hashlib.sha256(ca.read_bytes()).hexdigest(),uid=ca_stat.st_uid,mode=oct(ca_stat.st_mode&0o777),hostname_verification=True,certificate_verification=True)
    outcome['prior_attempt']=str(prior_attempt) if prior_attempt else None
    outcome['retained_prior_reservations']=dict(model_requests=prior_requests,executions=prior_executions,completion_tokens=prior_requests*2048,usage_unconfirmed=bool(prior_requests))
    files=[p for folder in ('pybox','tests') for p in (MAIN/folder).iterdir() if p.is_file()]
    files.extend([MAIN/'tools/runtime_validation.py',Path(__file__).resolve()])
    hashes={str(p.relative_to(MAIN)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    save(evidence/'source-hashes.json',hashes)
    for name in hashes:
        target=evidence/'sources'/name;target.parent.mkdir(mode=0o700,parents=True,exist_ok=True);shutil.copyfile(MAIN/name,target)
    owner_file=owner_stat=owner_bytes=test_owner=None
    original_owner=container.OWNER_FILE;original_admission=container._admission
    sequence=0

    def run(code):
        nonlocal sequence
        sequence+=1
        result=container.run_container(code,timeout_s=2,max_output_bytes=4096)
        save(evidence/('execution-%02d.json'%sequence),asdict(result))
        if result.container_id:
            runtime.records.append(dict(label='m6-%02d'%sequence,identity=result.identity,container_id=result.container_id,
                timeout_s=2,create_attempted=True,removed=result.removed,audit='execution-%02d.json'%sequence))
        return project_record(result.record)['execution']

    try:
        outcome['preflight']=runtime.preflight()
        test_owner=uuid.uuid4().hex
        require(test_owner not in {r['identity']['labels']['io.pybox.owner'] for r in runtime.sentinels},'owner collision')
        owner_file=container.ROOT/'tmp'/('m6-validation-owner-'+test_owner+'.json')
        owner_bytes=(json.dumps(dict(version=1,owner=test_owner))+'\n').encode()
        fd=os.open(owner_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as file:file.write(owner_bytes)
        owner_stat=owner_file.lstat()
        outcome['validation_identity']=dict(path=str(owner_file),owner=test_owner,removed=False,
            lock='parent holds actual installation lock; trusted harness uses outer admission')
        container.OWNER_FILE=owner_file;container._admission=nullcontext
        controller=RepairController(provider,budget,run)
        for index,problem in enumerate(CASES):
            # Counterbalance the first arm; model/seed/settings/caps are identical.
            arms=('stderr','structured') if index%2==0 else ('structured','stderr')
            for arm in arms:
                episode=controller.run(problem,arm)
                name=problem['id']+'-'+arm
                initial=episode['executions'][0]['record'] if episode['executions'] else {}
                if problem['intended_cause']=='oom':
                    count=initial.get('observed',{}).get('resources',{}).get('metrics',{}).get('memory.events',{}).get('last',{}).get('oom_kill',0)
                    require(count>0,'initial memory fixture lacked independent OOM counter evidence')
                elif problem['intended_cause']=='wall_timeout':
                    require('wall' in initial.get('lifecycle',{}).get('timeouts',[]),'initial wall fixture did not time out')
                else:require('TypeError' in initial.get('capture',{}).get('stderr',''),'initial exception fixture did not reproduce')
                save(evidence/(name+'.episode.json'),episode)
                outcome['episodes'].append(dict(name=name,success=episode['success'],status=episode['status'],
                    model_requests=len(episode['attempts']),executions=len(episode['executions']),
                    diagnosis_label_matches_fixture=episode['diagnosis_label_matches_fixture']))
                save(evidence/'status.json',dict(last_completed=name,episodes=len(outcome['episodes']),utc=stamp(),budget=budget.snapshot()))
                print(name+': '+episode['status'],flush=True)
                require(not budget.halted,'admission halted; inspect original result')
        require(all(hashlib.sha256((MAIN/name).read_bytes()).hexdigest()==sha for name,sha in hashes.items()),'source changed during run')
        require(len(outcome['episodes'])==8,'comparison incomplete')
        # A failed repair is an evaluation finding; it does not falsify harness completion.
        outcome['passed']=True
    except BaseException as exc:
        outcome['error']=type(exc).__name__+': '+str(exc).replace(key,'[REDACTED]')[:2048]
    finally:
        container.OWNER_FILE=original_owner;container._admission=original_admission
        outcome['budget']=budget.snapshot()
        provider.forget()
        if test_owner:
            try:
                ids=runtime.engine('m6-owner-final-query',['container','ls','--all','--quiet','--no-trunc','--filter','label=io.pybox.owner='+test_owner])['stdout'].split()
                for cid in ids:
                    d=json.loads(runtime.engine('m6-recover-inspect',['container','inspect','--format',container.INSPECT,cid])['stdout'])
                    labels=d['Config']['Labels'];identity=dict(name=d['Name'].removeprefix('/'),labels={k:labels[k] for k in ('io.pybox.owner','io.pybox.run','io.pybox.expires')})
                    container._Control(identity,cid);require(labels['io.pybox.owner']==test_owner and d['Id']==cid,'recovery identity mismatch')
                    if not any(r['container_id']==cid for r in runtime.records):runtime.records.append(dict(label='m6-recovery',identity=identity,container_id=cid,timeout_s=float(d['Config']['Cmd'][2])-1,create_attempted=True))
            except Exception as exc:outcome['recovery_error']=str(exc);outcome['passed']=False
        if owner_file:
            try:
                current=owner_file.lstat()
                require(owner_stat and (current.st_dev,current.st_ino)==(owner_stat.st_dev,owner_stat.st_ino) and stat.S_ISREG(current.st_mode)
                    and current.st_uid==os.getuid() and current.st_mode&0o777==0o600 and owner_file.read_bytes()==owner_bytes,'metadata changed')
                owner_file.unlink();outcome['validation_identity']['removed']=True
            except Exception as exc:outcome['identity_cleanup_error']=str(exc);outcome['passed']=False
        runtime.finish(outcome)
        if any(r.get('rescue_kill') for r in runtime.records):outcome['passed']=False;outcome['rescue_kill']=True
        # Scan exact credential without exposing it or its digest. Sources and evidence must be clean.
        found=any(key.encode() in p.read_bytes() for root in (evidence,MAIN/'pybox',MAIN/'tests',MAIN/'tools') for p in root.rglob('*') if p.is_file())
        outcome['credential_in_files']=found
        if found:outcome['passed']=False
        save(evidence/'outcome.json',outcome)
        key=None
        print(json.dumps({k:outcome.get(k) for k in ('passed','error','vm','episodes','allocation','credential_in_files')},indent=2),flush=True)
    return 0 if outcome['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true');parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--prior-attempt',type=Path,default=None)
    args=parser.parse_args()
    if not args.execute:parser.error('explicit --execute required')
    sys.exit(execute(args.evidence,args.prior_attempt))
