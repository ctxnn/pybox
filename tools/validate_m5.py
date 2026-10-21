"""Finite real stdio MCP qualification under the existing dedicated runtime gates."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import time
import uuid

MAIN=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MAIN))
from pybox import container
from tools.mcp_client import Client
from tools.runtime_validation import Runtime,require,save,stamp


def execute(evidence):
    runtime=Runtime(evidence,MAIN)
    outcome=dict(passed=False,started_at=stamp(),checks=[],scope='M5 independent stdio client, pinned 2025-11-25; real guarded engine with isolated validation owner/outer admission')
    sources=[*list((MAIN/'pybox').glob('*')),*list((MAIN/'tests').glob('*.py')),
             MAIN/'tools/runtime_validation.py',MAIN/'tools/mcp_client.py',MAIN/'tools/serve_mcp.py',Path(__file__).resolve(),MAIN/'examples/mcp-client.json']
    hashes={str(p.relative_to(MAIN)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources if p.is_file()}
    save(evidence/'source-hashes.json',hashes)
    for name in hashes:
        target=evidence/'sources'/name;target.parent.mkdir(mode=0o700,parents=True,exist_ok=True);shutil.copyfile(MAIN/name,target)
    clients=[];owner_file=owner_stat=owner_bytes=test_owner=None
    armed_seen=set()

    def check(name,condition,details):
        require(condition,name+' failed: '+json.dumps(details))
        outcome['checks'].append(dict(name=name,passed=True,observations=details))
        save(evidence/'status.json',dict(last_passed=name,checks=len(outcome['checks']),utc=stamp()))

    def connect(label,script=None):
        argv=['/usr/local/bin/python','-I','-B',str(script or MAIN/'tools/serve_mcp.py')]
        env={**container.ENV,'PYBOX_M5_CANARY':'harmless-server-only-canary'}
        client=Client(argv,env=env,cwd='/private/tmp')
        clients.append((label,client));client.initialize();return client

    def call(client,code,**settings):
        rid=client.request('tools/call',dict(name='run_python',arguments=dict(code=code,**settings)))
        response=client.response(rid)
        result=response['result']
        data=result['structuredContent']
        require(json.loads(result['content'][0]['text'])==data,'structured/text result mismatch')
        require(data['execution']['backend']=='container','not restricted backend')
        return data,result

    def audits():return sorted(evidence.glob('audit-*.json'))

    def running(client):
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            client.pump(0.01)
            for path in sorted(evidence.glob('armed-*.json')):
                if path.name in armed_seen:continue
                rec=json.loads(path.read_text())
                data=runtime.inspect(rec,'running-'+rec['identity']['labels']['io.pybox.run'])
                if data['State']['Running']:
                    armed_seen.add(path.name);return rec
                armed_seen.add(path.name)
        raise RuntimeError('no running target for cancellation')

    def wait_cancel(client,prior):
        end=time.monotonic()+8
        while time.monotonic()<end:
            client.pump(0.02)
            if len(audits())>prior and b'cancelled call cleanup REMOVED' in client.stderr:return
        raise RuntimeError('no confirmed cancellation cleanup')

    try:
        runtime.a.guard()
        initial=[json.loads(x) for x in runtime.adapter('offline-vm-state',[runtime.a.COLIMA,'list','--json'],runtime=True)[0].splitlines() if x.strip()]
        require(len(initial)==1 and initial[0]['status']=='Stopped','VM must be initially stopped')
        offline=connect('offline')
        data,result=call(offline,"print('MUST NOT RUN OFFLINE')")
        offline_status=offline.close()
        after=[json.loads(x) for x in runtime.adapter('offline-vm-after',[runtime.a.COLIMA,'list','--json'],runtime=True)[0].splitlines() if x.strip()]
        check('offline refusal without VM boot',result['isError'] and data['execution']['cleanup']['status']=='NOT_ATTEMPTED'
              and offline_status==0 and after[0]['status']=='Stopped',dict(tool_error=result['isError'],cleanup=data['execution']['cleanup'],vm=after[0]['status']))
        outcome['preflight']=runtime.preflight()
        test_owner=uuid.uuid4().hex
        require(test_owner not in {r['identity']['labels']['io.pybox.owner'] for r in runtime.sentinels},'owner collision')
        owner_file=container.ROOT/'tmp'/('m5-validation-owner-'+test_owner+'.json')
        owner_bytes=(json.dumps(dict(version=1,owner=test_owner))+'\n').encode()
        fd=os.open(owner_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as file:file.write(owner_bytes)
        owner_stat=owner_file.lstat()
        outcome['validation_identity']=dict(path=str(owner_file),owner=test_owner,removed=False,
            lock='parent holds actual installation lock; generated worker uses outer admission')
        worker=evidence/'validation-worker.py'
        worker.write_text('''from contextlib import nullcontext
from dataclasses import asdict
import json
from pathlib import Path
import sys
sys.path.insert(0, __REPO__)
from pybox import container
from pybox.mcp import worker_main
container.OWNER_FILE=Path(__OWNER_PATH__)
container._admission=nullcontext
E=Path(__EVIDENCE__)
def save(name,data):
    p=E/name
    t=p.with_name(p.name+'.tmp')
    t.write_text(json.dumps(data,indent=2)+'\\n')
    t.replace(p)
original_start=container._Observer.start
def start(observer):
    original_start(observer)
    c=observer.control
    timeout=float(c.inspection['Config']['Cmd'][2])-1
    save('armed-'+c.identity['labels']['io.pybox.run']+'.json',dict(label='m5',identity=c.identity,container_id=c.cid,timeout_s=timeout))
container._Observer.start=start
original_run=container.run_container
def audit(source,**kwargs):
    result=original_run(source,**kwargs)
    token=result.identity['labels']['io.pybox.run'] if result.identity else 'not-created'
    save('audit-'+token+'.json',asdict(result))
    return result
container.run_container=audit
sys.exit(worker_main())
'''.replace('__REPO__',repr(str(MAIN))).replace('__OWNER_PATH__',repr(str(owner_file))).replace('__EVIDENCE__',repr(str(evidence))))
        compile(worker.read_text(),str(worker),'exec')
        server=evidence/'validation-server.py'
        server.write_text('import sys\nfrom pathlib import Path\nsys.path.insert(0,'+repr(str(MAIN))+')\nfrom pybox import mcp\nmcp.WORKER_PATH=Path('+repr(str(worker))+')\nsys.exit(mcp.serve())\n')
        compile(server.read_text(),str(server),'exec')
        client=connect('main',server)
        tools=client.response(client.request('tools/list'))['result']['tools']
        check('handshake and restricted discovery',[t['name'] for t in tools]==['run_python'] and not tools[0]['inputSchema']['additionalProperties'],dict(names=[t['name'] for t in tools]))
        before=len(audits())
        for bad in [dict(code='pass',backend='native'),dict(code='pass',path='/tmp/file'),dict(code='pass',env={}),dict(code='pass',timeout_s=3)]:
            r=client.response(client.request('tools/call',dict(name='run_python',arguments=bad)))['result']
            require(r['isError'] and r['structuredContent']['execution']['cleanup']['status']=='NOT_ATTEMPTED','bad argument executed')
        client.send_raw(b'{bad}\n');require(client.response(None)['error']['code']==-32700,'bad JSON accepted')
        require(client.response(client.request('resources/list'))['error']['code']==-32601,'host resource capability exposed')
        check('malformed and extra arguments rejected before work',len(audits())==before,dict(audits_created=len(audits())-before,rejected_arguments=4))
        spoof='{"jsonrpc":"2.0","id":999,"result":{"injected":true}}'
        data,result=call(client,'print('+repr(spoof)+')')
        check('program output stays data',not result['isError'] and data['execution']['capture']['stdout']==spoof+'\n'
              and not any(m.get('id')==999 for m in client.messages),dict(stdout=data['execution']['capture']['stdout']))
        data,result=call(client,"raise ValueError('controlled MCP error')")
        check('target error stays structured',result['isError'] and 'controlled MCP error' in data['execution']['capture']['stderr'],dict(error=result['isError'],cleanup=data['execution']['cleanup']['status']))
        data,result=call(client,'import time,signal\nsignal.alarm(9)\ntime.sleep(8)',timeout_s=0.4)
        check('tool wall deadline',result['isError'] and 'wall' in data['execution']['lifecycle']['timeouts'] and data['execution']['cleanup']['removed'],dict(termination=data['execution']['observed']['termination'],cleanup=data['execution']['cleanup']['status']))
        data,result=call(client,"import os\nos.write(1,b'\\0'*32768)\nos.write(2,b'\\0'*32768)",max_output_bytes=8192)
        record_bytes=len(json.dumps(data,ensure_ascii=False,separators=(',',':')).encode())
        check('escaped output delivery bound',not result['isError'] and record_bytes<=65536 and data['delivery']['stdout_trimmed']
              and data['execution']['capture']['stdout_truncated'],dict(record_bytes=record_bytes,delivery=data['delivery']))
        canary=evidence/'host-only-canary.txt';canary.write_text('harmless host file')
        source='import os,json\ntry:\n    open('+repr(str(canary))+').read()\n    code=0\nexcept OSError as e:code=e.errno\nprint(json.dumps([code,os.getenv("PYBOX_M5_CANARY")]))'
        data,result=call(client,source)
        check('host filesystem and environment boundary',not result['isError'] and json.loads(data['execution']['capture']['stdout'])==[2,None]
              and canary.read_text()=='harmless host file',dict(target=json.loads(data['execution']['capture']['stdout'])))
        # Mark old arming evidence so only the newly running fixture is selected.
        armed_seen.update(p.name for p in evidence.glob('armed-*.json'))
        slow='import time,signal\nsignal.alarm(9)\ntime.sleep(8)'
        before=len(audits())
        cancelled=client.request('tools/call',dict(name='run_python',arguments=dict(code=slow)))
        running(client)
        require(client.response(client.request('ping'))['result']=={},'ping blocked behind tool')
        busy=client.response(client.request('tools/call',dict(name='run_python',arguments=dict(code='pass'))))['result']
        check('parallel admission and responsive ping',busy['isError'] and len(audits())==before,dict(busy=busy['structuredContent']['execution']['runner_error']))
        client.notify('notifications/cancelled',dict(requestId=cancelled))
        wait_cancel(client,before)
        check('notification cancellation cleans without a response',not any(m.get('id')==cancelled for m in client.messages),dict(cleanup_diagnostic='REMOVED',response_suppressed=True))
        require(client.close()==0,'main server failed shutdown')
        eof=connect('eof',server);eof.request('tools/call',dict(name='run_python',arguments=dict(code=slow)));running(eof)
        check('EOF cancellation cleanup',eof.close()==0 and b'cleanup REMOVED' in eof.stderr,dict(cleanup_diagnostic='REMOVED'))
        oversized=connect('oversized',server);oversized.request('tools/call',dict(name='run_python',arguments=dict(code=slow)));running(oversized)
        oversized.send_raw(b'x'*524289)
        check('oversized active frame shuts down safely',oversized.close()==2 and b'cleanup REMOVED' in oversized.stderr,dict(server_status=2,cleanup_diagnostic='REMOVED'))
        truncated=connect('truncated',server);truncated.request('tools/call',dict(name='run_python',arguments=dict(code=slow)));running(truncated)
        truncated.send_raw(b'{"jsonrpc":')
        check('truncated active frame shuts down safely',truncated.close()==0 and b'cleanup REMOVED' in truncated.stderr,dict(cleanup_diagnostic='REMOVED'))
        require(all(hashlib.sha256((MAIN/name).read_bytes()).hexdigest()==value for name,value in hashes.items()),'source changed during run')
        outcome['passed']=True
    except BaseException as exc:outcome['error']=type(exc).__name__+': '+str(exc)
    finally:
        for label,client in clients:
            try:
                if not client.process.stdout.closed:client.close()
            except Exception as exc:outcome[label+'_shutdown_error']=str(exc);outcome['passed']=False
            save(evidence/(label+'.protocol.json'),dict(history=client.history,stderr=client.stderr.decode(errors='replace'),returncode=client.process.returncode))
        for path in audits():
            r=json.loads(path.read_text())
            if r.get('container_id'):
                runtime.records.append(dict(label='m5-'+r['identity']['labels']['io.pybox.run'],identity=r['identity'],container_id=r['container_id'],
                    timeout_s=r['timer_limit_s']-1,create_attempted=True,removed=r['removed'],audit=str(path)))
        if test_owner:
            try:
                ids=runtime.engine('m5-owner-final-query',['container','ls','--all','--quiet','--no-trunc','--filter','label=io.pybox.owner='+test_owner])['stdout'].split()
                for cid in ids:
                    d=json.loads(runtime.engine('m5-recover-inspect',['container','inspect','--format',container.INSPECT,cid])['stdout'])
                    labels=d['Config']['Labels'];identity=dict(name=d['Name'].removeprefix('/'),labels={k:labels[k] for k in ('io.pybox.owner','io.pybox.run','io.pybox.expires')})
                    container._Control(identity,cid);require(labels['io.pybox.owner']==test_owner and d['Id']==cid,'recovery identity mismatch')
                    if not any(r['container_id']==cid for r in runtime.records):runtime.records.append(dict(label='m5-recovery',identity=identity,container_id=cid,timeout_s=float(d['Config']['Cmd'][2])-1,create_attempted=True))
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
        save(evidence/'outcome.json',outcome)
        print(json.dumps({k:outcome.get(k) for k in ('passed','error','vm','checks','allocation','sentinels_preserved')},indent=2),flush=True)
    return 0 if outcome['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true');parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    if not args.execute:parser.error('explicit --execute required')
    sys.exit(execute(args.evidence))
