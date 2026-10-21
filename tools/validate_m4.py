"""Real M4 CLI/collection qualification; finite fixtures on the dedicated VM."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import sys
import time
import uuid

MAIN=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MAIN))
from pybox import container
from tools.runtime_validation import Runtime, require, save, stamp

FIXTURES={
    'normal': "print('hello inspection')\n",
    'error': "raise ValueError('controlled target error')\n",
    'cpu': "import time,signal\nsignal.alarm(4)\nend=time.monotonic()+1.1\nfor i in range(100_000_000):\n    if i%1000==0 and time.monotonic()>=end:break\ntime.sleep(0.2)\nprint('computed')\n",
    'memory': "import os,time,signal\nsignal.alarm(4)\npid=os.fork()\nif pid==0:\n    with open('/proc/self/oom_score_adj','w') as f:f.write('1000')\n    blocks=[]\n    for _ in range(160):\n        blocks.append(bytearray(1048576))\n        time.sleep(0.003)\n    os._exit(0)\n_,status=os.waitpid(pid,0)\nprint(os.waitstatus_to_exitcode(status))\ntime.sleep(0.5)\n",
    'pids': "import os,time,signal\nsignal.alarm(4)\nchildren=[]\nfailed=0\nfor _ in range(36):\n    try:pid=os.fork()\n    except OSError:\n        failed+=1\n        continue\n    if pid==0:\n        time.sleep(0.6)\n        os._exit(0)\n    children.append(pid)\nfor pid in children:os.waitpid(pid,0)\nprint(len(children),failed)\ntime.sleep(0.2)\n",
    'timeout': "import time,signal\nsignal.alarm(9)\ntime.sleep(8)\n",
    'cancel': "import time,signal\nsignal.alarm(9)\ntime.sleep(8)\n",
    'policy': "print('MUST NOT RUN')\n",
}


def execute(evidence):
    runtime=Runtime(evidence,MAIN)
    outcome=dict(passed=False,started_at=stamp(),checks=[],scope='M4 real CLI/collection; isolated validation owner and outer admission')
    sources=[*list((MAIN/'pybox').glob('*')),*list((MAIN/'tests').glob('*.py')),
             MAIN/'tools/runtime_validation.py',Path(__file__).resolve(),MAIN/'tools/m4_supervisor.py']
    hashes={str(p.relative_to(MAIN)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources if p.is_file()}
    save(evidence/'source-hashes.json',hashes)
    for name in hashes:
        target=evidence/'sources'/name
        target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        shutil.copyfile(MAIN/name,target)
    owner_file=owner_stat=owner_bytes=test_owner=None

    def check(name,condition,details):
        require(condition,name+' failed: '+json.dumps(details))
        outcome['checks'].append(dict(name=name,passed=True,observations=details))
        save(evidence/'status.json',dict(last_passed=name,checks=len(outcome['checks']),utc=stamp()))

    def supervisor(label,source,timeout_s=2,policy=False,send_signal=None):
        result_path=evidence/(label+'.result.json')
        armed_path=evidence/(label+'.armed.json')
        (evidence/(label+'.source.py')).write_text(source)
        argv=['/usr/local/bin/python','-B',str(MAIN/'tools/m4_supervisor.py'),'--owner-file',str(owner_file),
              '--result',str(result_path),'--armed',str(armed_path),'--timeout',str(timeout_s)]
        if policy:argv+=['--policy-rejection']
        if send_signal is None:
            capture=runtime.command(label+'-cli',argv,timeout=12,allowed=(0,1,124,125,130),source=source.encode())
        else:
            original=container.subprocess.Popen
            owned=[]
            def launch(*args,**kwargs):
                process=original(*args,**kwargs)
                if args[0]==argv:owned.append(process)
                return process
            with ThreadPoolExecutor(max_workers=1) as pool:
                from unittest.mock import patch
                with patch.object(container.subprocess,'Popen',side_effect=launch):
                    future=pool.submit(runtime.command,label+'-cli',argv,12,False,(130,),source.encode())
                    deadline=time.monotonic()+3
                    while time.monotonic()<deadline:
                        if armed_path.exists():
                            armed=json.loads(armed_path.read_text())
                            rec=dict(label=label,identity=armed['identity'],container_id=armed['container_id'],timeout_s=timeout_s)
                            state=runtime.inspect(rec,label+'-before-signal')['State']
                            if state['Running']:break
                        time.sleep(0.03)
                    else:raise RuntimeError('supervisor did not reach a running target')
                    require(len(owned)==1 and owned[0].poll() is None,'supervisor identity not live')
                    save(evidence/(label+'.signal.json'),dict(pid=owned[0].pid,signal=send_signal.name,utc=stamp(),target=rec))
                    os.kill(owned[0].pid,send_signal)
                    capture=future.result(timeout=12)
        require(result_path.exists(),'no completed supervised result')
        result=json.loads(result_path.read_text())
        if result['container_id']:
            runtime.records.append(dict(label=label,identity=result['identity'],container_id=result['container_id'],
                timeout_s=timeout_s,create_attempted=True,removed=result['removed'],production_result=str(result_path)))
        record=json.loads(capture['stdout'])
        require(record==result['record'] and record['schema_version']==1,'CLI record differs from returned result')
        require(result['identity']['labels']['io.pybox.owner']==test_owner,'wrong validation installation identity')
        require(result['removed'] and result['cleanup_status']=='REMOVED','production cleanup unconfirmed')
        require(not list(container._attempt_directory().iterdir()),'production attempt journal not cleared')
        return result,capture

    try:
        outcome['preflight']=runtime.preflight()
        test_owner=uuid.uuid4().hex
        require(test_owner not in {r['identity']['labels']['io.pybox.owner'] for r in runtime.sentinels},'validation owner collided')
        owner_file=container.ROOT/'tmp'/('m4-validation-owner-'+test_owner+'.json')
        owner_bytes=(json.dumps(dict(version=1,owner=test_owner))+'\n').encode()
        fd=os.open(owner_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as file:file.write(owner_bytes)
        owner_stat=owner_file.lstat()
        outcome['validation_identity']=dict(path=str(owner_file),owner=test_owner,sha256=hashlib.sha256(owner_bytes).hexdigest(),
            lock='parent holds real installation admission; child uses outer admission',removed=False)
        for label,source in FIXTURES.items():
            result,capture=supervisor(label,source,timeout_s=0.4 if label=='timeout' else 2,
                                      policy=label=='policy',send_signal=signal.SIGINT if label=='cancel' else None)
            metrics=result['resources'].get('metrics',{})
            reasons={r['code'] for r in result['record']['explanations']}
            if label=='normal':condition=result['stdout']=='hello inspection\n' and capture['returncode']==0 and result['returncode']==0
            elif label=='error':condition=capture['returncode']==1 and result['returncode']==1 and 'controlled target error' in result['stderr']
            elif label=='cpu':condition=capture['returncode']==0 and result['returncode']==0 and 'CPU_THROTTLING_OBSERVED' in reasons
            elif label=='memory':condition=capture['returncode']==0 and result['stdout']=='-9\n' and 'OOM_KILL_COUNTER_OBSERVED' in reasons
            elif label=='pids':condition=capture['returncode']==0 and result['stdout']=='30 6\n' and 'TASK_LIMIT_EVENT_OBSERVED' in reasons
            elif label=='timeout':condition=capture['returncode']==124 and result['timed_out'] and result['termination_evidence']['pybox_kill_sent']
            elif label=='cancel':condition=capture['returncode']==130 and result['cancelled'] and result['termination_evidence']['pybox_kill_sent']
            else:condition=capture['returncode']==125 and not result['record']['observed']['policy_verified_before_start'] and not result['stdout'] and not any(o['phase']=='start' for o in result['operations'])
            if label not in ('timeout','cancel','policy'):require(result['runner_error'] is None,'unexpected runner error')
            observed={name:dict(last=value['last'],delta=value.get('delta')) if value else None
                      for name,value in metrics.items() if name in ('memory.events','memory.peak','pids.events','cpu.stat')}
            check(label,condition,dict(cli_status=capture['returncode'],target_status=result['returncode'],
                collector_status=result['resources']['status'],samples=result['resources'].get('sample_count'),
                metrics=observed,explanations=sorted(reasons),lifecycle_elapsed_s=result['lifecycle_elapsed_s'],
                final_counters_complete=result['resources'].get('final_counters_complete')))
        require(all(hashlib.sha256((MAIN/name).read_bytes()).hexdigest()==value for name,value in hashes.items()),'source changed during validation')
        outcome['passed']=True
    except BaseException as exc:
        outcome['error']=type(exc).__name__+': '+str(exc)
    finally:
        if test_owner is not None:
            try:
                remaining=runtime.engine('validation-owner-final-query',['container','ls','--all','--quiet','--no-trunc','--filter','label=io.pybox.owner='+test_owner])['stdout'].split()
                for cid in remaining:
                    data=json.loads(runtime.engine('recover-owned-validation-object',['container','inspect','--format',container.INSPECT,cid])['stdout'])
                    labels=data['Config']['Labels']
                    identity=dict(name=data['Name'].removeprefix('/'),labels={k:labels[k] for k in ('io.pybox.owner','io.pybox.run','io.pybox.expires')})
                    container._Control(identity,cid)
                    require(data['Id']==cid and labels['io.pybox.owner']==test_owner,'validation recovery identity mismatch')
                    if not any(r.get('container_id')==cid for r in runtime.records):
                        runtime.records.append(dict(label='recover-'+identity['labels']['io.pybox.run'],identity=identity,
                            container_id=cid,timeout_s=2,create_attempted=True))
            except Exception as exc:outcome['validation_recovery_error']=str(exc);outcome['passed']=False
        if owner_file is not None:
            try:
                current=owner_file.lstat()
                require(owner_stat is not None and (current.st_dev,current.st_ino)==(owner_stat.st_dev,owner_stat.st_ino)
                    and stat.S_ISREG(current.st_mode) and current.st_uid==os.getuid() and current.st_mode&0o777==0o600
                    and owner_file.read_bytes()==owner_bytes,'validation metadata changed; preserve it')
                owner_file.unlink();outcome['validation_identity']['removed']=True
            except Exception as exc:outcome['identity_cleanup_error']=str(exc);outcome['passed']=False
        runtime.finish(outcome)
        print(json.dumps({k:outcome.get(k) for k in ('passed','error','vm','checks','allocation','sentinels_preserved')},indent=2),flush=True)
    return 0 if outcome['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    if not args.execute:parser.error('explicit --execute required')
    sys.exit(execute(args.evidence))
