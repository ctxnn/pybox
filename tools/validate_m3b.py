"""Explicit finite M3b comparisons; never execute on the unsafe native backend."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime
import errno
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

MAIN=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MAIN))
from pybox import container
from tools import m3b_fixtures as fixtures
from tools.runtime_validation import Runtime,require,save,stamp


def execute(evidence,recover_evidence=None,resume_evidence=None):
    recover=[]
    if recover_evidence:
        prior=json.loads((recover_evidence/'outcome.json').read_text())
        require(prior.get('vm')=='Stopped' and not prior['passed'],'not a failed stopped attempt')
        recover=[r for r in prior['fixtures'] if r.get('container_id') and not r.get('removed')]
    runtime=Runtime(evidence,MAIN,recover)
    outcome=dict(passed=False,started_at=stamp(),checks=[],scope='M3b finite controlled comparisons; no M3c/MCP/agent')
    sources=[*list((MAIN/'pybox').glob('*.py')),*list((MAIN/'tests').glob('*.py')),
             MAIN/'tools/runtime_validation.py', MAIN/'tools/m3b_fixtures.py',Path(__file__).resolve()]
    hashes={str(p.relative_to(MAIN)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    save(evidence/'source-hashes.json',hashes)
    pool=None
    future=None

    def check(name,condition,details):
        require(condition,name+' behavioral gate failed: '+json.dumps(details))
        outcome['checks'].append(dict(name=name,passed=True,observations=details))
        save(evidence/'status.json',dict(last_passed=name,checks=len(outcome['checks']),utc=stamp()))

    def run(label,source,changes=None,cap=65536,storage=False):
        rec=runtime.create(label,source,changes)
        before=runtime.container_kib(rec,label+'-storage-before') if storage else None
        capture=runtime.attach(rec,source,cap)
        require(capture['returncode']==0 and (cap<65536 or not capture['stderr_truncated']),'controlled non-timer probe failed')
        if storage:
            after=runtime.container_kib(rec,label+'-storage-after')
            rec['storage_kib']=dict(before=before,after=after,delta=after-before)
        result=json.loads(capture['stdout']) if cap==65536 else dict(stdout_bytes=len(capture['stdout'].encode()),
                    stderr_bytes=len(capture['stderr'].encode()),stdout_truncated=capture['stdout_truncated'],
                    stderr_truncated=capture['stderr_truncated'],output_complete=capture['output_complete'])
        rec['observation']=result
        runtime.cleanup(rec)
        return result,rec

    def basic_checks():
        host=evidence/'host-canary.txt'; host.write_text('Harmless host-only M3b canary '+uuid.uuid4().hex)
        previous=os.environ.get('PYBOX_M3B_HOST_CANARY')
        os.environ['PYBOX_M3B_HOST_CANARY']='harmless-parent-only-canary'
        try: protected,_=run('host-boundary',fixtures.host_boundary(host))
        finally:
            if previous is None: os.environ.pop('PYBOX_M3B_HOST_CANARY',None)
            else: os.environ['PYBOX_M3B_HOST_CANARY']=previous
        check('host filesystem and environment boundary',protected['host_errno']==errno.ENOENT and protected['image_readable']
              and protected['canary_env'] is None,protected)

        protected,_=run('readonly-root',fixtures.FILESYSTEM)
        baseline,_=run('writable-root-baseline',fixtures.FILESYSTEM,dict(readonly=False))
        check('read-only root',protected['root_write']==errno.EROFS and baseline['root_write']==0,dict(protected=protected,baseline=baseline))
        protected,_=run('scratch-16m',fixtures.SCRATCH)
        baseline,_=run('scratch-20m-baseline',fixtures.SCRATCH,dict(tmpfs=container.TMPFS.replace('16m','20m')))
        check('bounded scratch',protected['errno']==errno.ENOSPC and 0<protected['bytes_written']<=16*1048576
              and baseline==dict(bytes_written=17*1048576,errno=0),dict(protected=protected,baseline=baseline))
        protected,_=run('scratch-noexec',fixtures.NOEXEC)
        baseline,_=run('scratch-exec-baseline',fixtures.NOEXEC,dict(tmpfs=container.TMPFS.replace(',noexec',',exec')))
        check('noexec scratch',protected['errno']==errno.EACCES and 'noexec' in protected['tmp_options'].split(',')
              and baseline['errno']==0 and baseline['returncode']==0 and 'noexec' not in baseline['tmp_options'].split(','),dict(protected=protected,baseline=baseline))

        protected,_=run('nonroot',fixtures.IDENTITY)
        baseline,_=run('root-identity-baseline',fixtures.IDENTITY,dict(user='0:0'))
        check('non-root identity',protected['uid']==10000 and protected['gid']==10000 and protected['root_errno']==errno.EACCES
              and protected['setuid_errno']==errno.EPERM and int(protected['cap_eff'],16)==0 and int(protected['cap_bnd'],16)==0
              and baseline['uid']==0 and baseline['root_errno']==0 and baseline['setuid_errno']==0,dict(protected=protected,baseline=baseline))
        protected,_=run('drop-chown-capability',fixtures.CHOWN,dict(user='0:0'))
        baseline,_=run('chown-capability-baseline',fixtures.CHOWN,dict(user='0:0',cap_add=['CHOWN']))
        check('capability drop under root comparison',protected['errno']==errno.EPERM and baseline['errno']==0
              and baseline['file_uid']==10001,dict(protected=protected,baseline=baseline))
        protected,_=run('no-new-privileges',fixtures.NNP)
        baseline,_=run('nnp-unset-baseline',fixtures.NNP,dict(nnp=False))
        check('no-new-privileges kernel behavior',protected['nnp_before']==1 and protected['nnp_after']==1
              and protected['clear_result']==-1 and protected['clear_errno']==errno.EINVAL and protected['filter_install']==0
              and baseline['nnp_before']==0 and baseline['filter_install']==-1 and baseline['filter_errno'] in (errno.EACCES,errno.EPERM),
              dict(protected=protected,baseline=baseline,limit='kernel flag and unprivileged filter permission; no setuid-binary exec transition tested'))
        protected,_=run('default-seccomp',fixtures.SECCOMP)
        baseline,_=run('seccomp-unconfined-baseline',fixtures.SECCOMP,dict(seccomp=False))
        check('default seccomp syscall restriction',protected['result']==-1 and protected['errno']==errno.EPERM
              and protected['seccomp']=='2' and baseline['result']>=0 and baseline['seccomp']=='0',dict(protected=protected,baseline=baseline))
        protected,_=run('nofile-128',fixtures.DESCRIPTORS)
        baseline,_=run('nofile-192-baseline',fixtures.DESCRIPTORS,dict(nofile=192))
        check('descriptor ceiling',protected['limits']==[128,128] and protected['errno']==errno.EMFILE and protected['opened']<128
              and not protected['raised'] and baseline['limits']==[192,192] and baseline['opened']>128 and baseline['errno']==errno.EMFILE,
              dict(protected=protected,baseline=baseline))


    try:
        for ref,expected in [('HEAD','1e07a74c7fe202c89fc11143a66db7a5b84efe9e'),
                             ('refs/heads/main','262096c3e49a8332650b92c02e5723da9f50a6a3'),
                             ('refs/heads/checkpoint/m3a-step2','45730cc54d5954b739eb26c6f5e5e7bdc6efb2b9')]:
            actual=runtime.command('git-ref',['/usr/bin/git','-C',str(MAIN),'rev-parse',ref],5)['stdout'].strip()
            require(actual==expected,'preserved ref changed')
        outcome['preflight']=runtime.preflight()
        if resume_evidence is None:
            basic_checks()
        else:
            prior=json.loads((resume_evidence/'outcome.json').read_text())
            expected=['host filesystem and environment boundary','read-only root','bounded scratch','noexec scratch',
                      'non-root identity','capability drop under root comparison','no-new-privileges kernel behavior',
                      'default seccomp syscall restriction','descriptor ceiling']
            require(prior.get('vm')=='Stopped' and not prior['passed'] and
                    [c['name'] for c in prior['checks']]==expected and all(c['passed'] for c in prior['checks']),
                    'resume is not the nine completed finite comparisons')
            old_hashes=json.loads((resume_evidence/'source-hashes.json').read_text())
            for name,value in old_hashes.items():
                if name.startswith('pybox/') or name=='tools/runtime_validation.py':
                    require(hashlib.sha256((MAIN/name).read_bytes()).hexdigest()==value,'runtime changed since completed comparisons')
            current_sources={'readonly-root':fixtures.FILESYSTEM,'scratch-16m':fixtures.SCRATCH,'scratch-noexec':fixtures.NOEXEC,
                             'nonroot':fixtures.IDENTITY,'drop-chown-capability':fixtures.CHOWN,'no-new-privileges':fixtures.NNP,
                             'default-seccomp':fixtures.SECCOMP,'nofile-128':fixtures.DESCRIPTORS,
                             'host-boundary':fixtures.host_boundary(resume_evidence/'host-canary.txt')}
            for label,source in current_sources.items():
                records=[r for r in prior['fixtures'] if r['label']==label and r.get('removed')]
                require(len(records)==1 and records[0]['source_sha256']==hashlib.sha256(source.encode()).hexdigest(),
                        'completed fixture binding changed: '+label)
            outcome['checks']=prior['checks']
            outcome['continued_from']=str(resume_evidence)
        token=uuid.uuid4().hex
        net=dict(name='pybox-m3b-'+token,labels={'io.pybox.owner':runtime.owner,'io.pybox.run':token,'io.pybox.expires':str(int(time.time())+120)})
        runtime.networks.append(net)
        args=['network','create','--driver=bridge','--internal']
        for k,v in net['labels'].items(): args+=['--label',k+'='+v]
        net['id']=runtime.engine('internal-network-create',args+[net['name']],5)['stdout'].strip()
        require(re.fullmatch('[0-9a-f]{64}',net['id']),'invalid fixture network ID')
        network_data=json.loads(runtime.engine('internal-network-preflight',['network','inspect',net['id']])['stdout'])[0]
        require(network_data['Id']==net['id'] and network_data['Name']==net['name'] and network_data['Internal'] is True
                and network_data['Driver']=='bridge' and not network_data['Containers']
                and all(network_data['Labels'].get(k)==v for k,v in net['labels'].items()),'internal network gate failed before traffic')
        server=runtime.create('private-network-server',fixtures.SERVER,dict(network=net['name']),timeout_s=7)
        pool=ThreadPoolExecutor(max_workers=1)
        future=pool.submit(runtime.attach,server,fixtures.SERVER)
        time.sleep(0.25)
        data=runtime.inspect(server,'private-network-server-running')
        require(data['State']['Running'],'fixture server not running')
        address=data['NetworkSettings']['Networks'][net['name']]['IPAddress']
        require(ipaddress.ip_address(address).is_private,'not private fixture address')
        protected,_=run('network-none',fixtures.network_probe(address))
        baseline,_=run('internal-network-baseline',fixtures.network_probe(address),dict(network=net['name']))
        check('external TCP and synthetic DNS isolation',fixtures.network_gate(protected,baseline),
              dict(protected=protected,baseline=baseline,scope='private internal fixture network; one TCP canary and one DNS .invalid query, no Internet'))
        server_result=future.result(timeout=10)
        require(json.loads(server_result['stdout'])==dict(seen=['dns','tcp']),'fixture server did not see both controls')
        future=None; pool.shutdown(wait=True); pool=None
        runtime.cleanup(server)

        protected,protected_rec=run('output-log-none',fixtures.FLOOD,cap=4096,storage=True)
        baseline,baseline_rec=run('output-json-log-baseline',fixtures.FLOOD,dict(log='json-file'),cap=4096,storage=True)
        check('bounded output capture and disabled engine log',all(x['stdout_bytes']==4096 and x['stderr_bytes']==4096
              and x['stdout_truncated'] and x['stderr_truncated'] and x['output_complete'] for x in (protected,baseline))
              and not protected_rec['terminal']['LogPath'] and baseline_rec['terminal']['LogPath']
              and protected_rec['storage_kib']['delta']<=64 and baseline_rec['storage_kib']['delta']>=512,
              dict(protected=protected,baseline=baseline,log_none_storage_kib=protected_rec['storage_kib'],json_log_storage_kib=baseline_rec['storage_kib']))

        for name in ('SIGTERM','SIGSTOP'):
            source=fixtures.pid1_signal(name)
            rec=runtime.create('pid1-'+name.lower(),source)
            pool=ThreadPoolExecutor(max_workers=1)
            future=pool.submit(runtime.attach,rec,source)
            time.sleep(0.5)
            running=runtime.inspect(rec,rec['label']+'-after-signal')
            require(running['State']['Running'],'timer/target exited before signal observation')
            proc=runtime.engine(rec['label']+'-actual-pid1',['container','exec',rec['container_id'],'/bin/cat','/proc/1/status','/proc/1/cmdline'])['stdout']
            save(evidence/(rec['label']+'.pid1.json'),dict(readback=proc))
            result=future.result(timeout=7)
            future=None; pool.shutdown(wait=True); pool=None
            state=rec['terminal']['State']
            life=(datetime.datetime.fromisoformat(state['FinishedAt'].replace('Z','+00:00'))-
                  datetime.datetime.fromisoformat(state['StartedAt'].replace('Z','+00:00'))).total_seconds()
            observation=json.loads(result['stdout'])
            check('PID 1 '+name+' deadline',observation==dict(signal=name,kill_returned=True)
                  and 'Name:\ttimeout\n' in proc and 'Pid:\t1\n' in proc and '\nState:\tT' not in proc
                  and state['ExitCode']==137 and not state['OOMKilled'] and not state['Error'] and 2.8<=life<4.5,
                  dict(target=observation,engine_lifetime_s=life,state=state,mac_primary_bypassed=True,
                       meaning='timer-only bounded fixture; no observer engine KILL'))
            rec['timer_lifetime_s']=life
            runtime.cleanup(rec)

        require(all(hashlib.sha256((MAIN/name).read_bytes()).hexdigest()==value for name,value in hashes.items()),'source changed during validation')
        require(not any(rec.get('rescue_kill') for rec in runtime.records),'rescue kill prevents passing this milestone')
        outcome['passed']=True
    except BaseException as exc:
        outcome['error']=type(exc).__name__+': '+str(exc)
    finally:
        if future is not None:
            try: future.result(timeout=12)
            except BaseException as exc: outcome['attach_error']=str(exc)
        if pool is not None: pool.shutdown(wait=True)
        runtime.finish(outcome)
        print(json.dumps({k:outcome.get(k) for k in ['passed','error','vm','checks','sentinels_preserved','allocation']},indent=2),flush=True)
    return 0 if outcome['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--recover-evidence',type=Path)
    parser.add_argument('--resume-evidence',type=Path)
    args=parser.parse_args()
    if not args.execute: parser.error('explicit --execute required')
    sys.exit(execute(args.evidence,args.recover_evidence,args.resume_evidence))
