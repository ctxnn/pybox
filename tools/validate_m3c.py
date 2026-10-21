"""Explicit M3c finite resource experiments on the dedicated VM only."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import time

MAIN=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MAIN))
from pybox import container
from tools import m3c_fixtures as fixtures
from tools.m3c_evidence import parse_observer, summarize
from tools.runtime_validation import Runtime, require, save, stamp


def execute(evidence):
    runtime=Runtime(evidence,MAIN)
    outcome=dict(passed=False,started_at=stamp(),checks=[],scope='M3c controlled resource evidence; no production collector or MCP yet')
    sources=[*list((MAIN/'pybox').glob('*.py')),*list((MAIN/'tests').glob('*.py')),
             MAIN/'tools/runtime_validation.py',*list((MAIN/'tools').glob('m3c_*')),Path(__file__).resolve()]
    hashes={str(p.relative_to(MAIN)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources if p.is_file()}
    save(evidence/'source-hashes.json',hashes)
    for name,expected in hashes.items():
        target=evidence/'sources'/name
        target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        shutil.copyfile(MAIN/name,target)
        require(hashlib.sha256(target.read_bytes()).hexdigest()==expected,'source archive mismatch')

    def check(name, condition, details):
        require(condition,name+' behavioral gate failed: '+json.dumps(details))
        outcome['checks'].append(dict(name=name,passed=True,observations=details))
        save(evidence/'status.json',dict(last_passed=name,checks=len(outcome['checks']),utc=stamp()))

    def run(label,source,changes=None,timeout_s=7):
        rec=runtime.create(label,source,changes,timeout_s=timeout_s)

        def attach():
            capture=runtime.engine(label+'-start',['container','start','--attach','--interactive',rec['container_id']],
                                   timeout_s+3,allowed=(0,23,137,152),source=source.encode())
            rec['capture']=capture
            rec['terminal']=runtime.inspect(rec,label+'-terminal')
            state=rec['terminal']['State']
            require(state['Status']=='exited' and not state['Running'] and not state['Error']
                    and capture['returncode']==state['ExitCode'],'attach/terminal mismatch')
            return capture

        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(attach)
            try:
                for _ in range(25):
                    data=runtime.inspect(rec,label+'-waiting-for-start')
                    if data['State']['Running']: break
                    require(data['State']['Status']=='created','target exited before observer')
                    time.sleep(0.02)
                require(data['State']['Running'] and type(data['State']['Pid']) is int and data['State']['Pid']>1,'no live guest PID')
                pid=data['State']['Pid']
                observed=runtime.command(label+'-trusted-guest-observer',
                    [runtime.a.COLIMA,'ssh','--profile','pybox','--','sudo','sh','-s','--',str(pid),rec['container_id']],
                    timeout=12,runtime=True,source=(MAIN/'tools/m3c_observer.sh').read_bytes(),cap=262144)
                require(not observed['stdout_truncated'] and not observed['stderr_truncated'] and not observed['stderr'],'incomplete/diagnostic observer capture')
                provenance=parse_observer(observed['stdout'],rec['container_id'],pid,timeout_s+1)
                rec['kernel_evidence']=summarize(provenance)
                save(evidence/(label+'.kernel.json'),provenance)
                capture=future.result(timeout=timeout_s+4)
            finally:
                # Attach has its own finite deadline; collect it before exact cleanup.
                if not future.done():
                    try: future.result(timeout=timeout_s+4)
                    except BaseException as exc: rec['attach_error']=str(exc)
        kernel=rec['kernel_evidence']
        limits=kernel['limits']
        require(limits['memory.max']==str((changes or {}).get('memory_mib',128)*1048576)
                and limits['memory.swap.max']=='0' and limits['memory.oom.group']=='0'
                and limits['pids.max']==str((changes or {}).get('pids',32)),'kernel resource limit mismatch')
        quota,period=map(int,limits['cpu.max'].split())
        require(quota/period==(changes or {}).get('cpus',0.5),'kernel CPU quota mismatch')
        require(kernel['memory.swap.current'] is not None and kernel['memory.swap.current']['max']==0,'observed swapping in no-extra-swap fixture')
        state=rec['terminal']['State']
        rec['engine_lifetime_s']=(datetime.datetime.fromisoformat(state['FinishedAt'].replace('Z','+00:00'))-
                                  datetime.datetime.fromisoformat(state['StartedAt'].replace('Z','+00:00'))).total_seconds()
        rec['target_observations']=[json.loads(line) for line in capture['stdout'].splitlines()]
        rec['observer_metadata']=provenance['metadata']
        runtime.cleanup(rec)
        return rec

    try:
        for ref,expected in [('HEAD','1e07a74c7fe202c89fc11143a66db7a5b84efe9e'),
                             ('refs/heads/main','262096c3e49a8332650b92c02e5723da9f50a6a3'),
                             ('refs/heads/checkpoint/m3a-step2','45730cc54d5954b739eb26c6f5e5e7bdc6efb2b9')]:
            actual=runtime.command('git-ref',['/usr/bin/git','-C',str(MAIN),'rev-parse',ref],5)['stdout'].strip()
            require(actual==expected,'preserved ref changed')
        outcome['preflight']=runtime.preflight()
        protected=run('memory-128m',fixtures.MEMORY)
        baseline=run('memory-192m-baseline',fixtures.MEMORY,dict(memory_mib=192))
        p,b=protected['kernel_evidence'],baseline['kernel_evidence']
        check('memory OOM and no extra swap',p['memory.events']['delta']['oom_kill']>=1 and p['memory.events']['delta']['oom']>=1
              and b['memory.events']['delta']['oom_kill']==0 and p['memory.events.local']['delta']['oom_kill']>=1
              and protected['target_observations']==[dict(child_exit=-9)] and baseline['target_observations']==[dict(child_exit=0)]
              and protected['capture']['returncode']==baseline['capture']['returncode']==0
              and p['memory.peak'] is not None and b['memory.peak'] is not None and b['memory.peak']['max']>134217728,
              dict(protected=p,baseline=b,scope='one 160 MiB child allocation; parent survives to permit independent post-OOM reads'))

        for kind,source in [('processes',fixtures.PROCESSES),('threads',fixtures.THREADS)]:
            protected=run('pids-32-'+kind,source)
            baseline=run('pids-48-'+kind+'-baseline',source,dict(pids=48))
            p,b=protected['kernel_evidence'],baseline['kernel_evidence']
            po,bo=protected['target_observations'][0],baseline['target_observations'][0]
            check('PID controller counts '+kind,p['pids.events']['delta']['max']>=1 and b['pids.events']['delta']['max']==0
                  and p['pids.current']['max']==32 and b['pids.current']['max']==38 and po['created']==30 and bo['created']==36
                  and len(po['failures'])==6 and not bo['failures']
                  and protected['capture']['returncode']==baseline['capture']['returncode']==0,
                  dict(protected=p,baseline=b,target_protected=po,target_baseline=bo))

        protected=run('cpu-half-core',fixtures.cpu())
        baseline=run('cpu-one-core-baseline',fixtures.cpu(),dict(cpus=1))
        p,b=protected['kernel_evidence'],baseline['kernel_evidence']
        pu,bu=p['cpu.stat']['delta']['usage_usec'],b['cpu.stat']['delta']['usage_usec']
        check('CPU bandwidth throttles without killing',protected['capture']['returncode']==baseline['capture']['returncode']==0
              and p['cpu.stat']['delta']['nr_throttled']>=5 and p['cpu.stat']['delta']['throttled_usec']>0
              and 700000<pu<1600000 and 1500000<bu<2800000 and bu>pu*1.4,
              dict(protected=p,baseline=b,target_protected=protected['target_observations'],target_baseline=baseline['target_observations']))

        timer=run('cpu-guest-wall-timer',fixtures.cpu(8),timeout_s=2)
        k=timer['kernel_evidence']
        check('CPU quota and wall termination are separate',timer['capture']['returncode']==137 and not timer['terminal']['State']['OOMKilled']
              and 2.8<timer['engine_lifetime_s']<4.5 and k['cpu.stat']['delta']['nr_throttled']>=5
              and k['memory.events']['delta']['oom_kill']==0 and not timer['target_observations'],
              dict(engine_lifetime_s=timer['engine_lifetime_s'],kernel=k,meaning='no engine KILL; exit/timestamps consistent with guest timer, not quota killing'))

        for mode,code in [('default',152),('catch',23),('ignore',137),('sleep',0)]:
            rec=run('rlimit-cpu-'+mode,fixtures.rlimit(mode))
            k=rec['kernel_evidence']
            require(re.search(r'Max cpu time\s+1\s+2\s+seconds',rec['observer_metadata']['child_limits']), 'RLIMIT_CPU not independently read back')
            usage=k['cpu.stat']['delta']['usage_usec']/1000000
            extra=(0.7<usage<1.5 if mode in ('default','catch') else 1.6<usage<2.5 if mode=='ignore' else usage<0.4)
            check('Linux RLIMIT_CPU '+mode,rec['capture']['returncode']==code and not rec['terminal']['State']['OOMKilled']
                  and k['memory.events']['delta']['oom_kill']==0 and extra and rec['engine_lifetime_s']<7,
                  dict(returncode=code,engine_lifetime_s=rec['engine_lifetime_s'],observed_cpu_s=usage,kernel=k,
                       target=rec['target_observations'],kernel_limits=rec['observer_metadata']['child_limits']))

        require(all(hashlib.sha256((MAIN/name).read_bytes()).hexdigest()==value for name,value in hashes.items()),'source changed during validation')
        require(not any(rec.get('rescue_kill') for rec in runtime.records),'rescue kill prevents passing')
        outcome['passed']=True
    except BaseException as exc:
        outcome['error']=type(exc).__name__+': '+str(exc)
    finally:
        runtime.finish(outcome)
        print(json.dumps({k:outcome.get(k) for k in ['passed','error','vm','checks','sentinels_preserved','allocation']},indent=2),flush=True)
    return 0 if outcome['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    if not args.execute: parser.error('explicit --execute required')
    sys.exit(execute(args.evidence))
