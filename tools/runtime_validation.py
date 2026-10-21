"""Shared, explicitly invoked finite validation on the dedicated Mac runtime."""
import copy
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import threading
import time

from pybox import container


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def save(path, data):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def create_args(identity, timeout_s, changes):
    args = container._create_args(identity, timeout_s)
    args[args.index('io.pybox.checkpoint=m3a-step4')] = 'io.pybox.checkpoint=m3b-fixture'
    replacements = {'user': ('--user=10000:10000', '--user='), 'network': ('--network=none', '--network='),
                    'log': ('--log-driver=none', '--log-driver=')}
    for key, (old, prefix) in replacements.items():
        if key in changes:
            args[args.index(old)] = prefix + changes[key]
    if changes.get('readonly') is False:
        args.remove('--read-only')
    if 'tmpfs' in changes:
        args[args.index('--tmpfs') + 1] = '/tmp:' + changes['tmpfs']
    if 'nofile' in changes:
        n = changes['nofile']
        args[args.index('--ulimit') + 1] = 'nofile=%d:%d' % (n, n)
    # Finite M3c controls, deliberately unavailable through the production API.
    resource_controls = {'memory_mib': (192,), 'pids': (48,), 'cpus': (1,)}
    for key, allowed in resource_controls.items():
        if key in changes:
            require(type(changes[key]) is int and changes[key] in allowed, 'invalid bounded resource control: ' + key)
    if 'memory_mib' in changes:
        for old, prefix in [('--memory=128m', '--memory='), ('--memory-swap=128m', '--memory-swap=')]:
            args[args.index(old)] = prefix + str(changes['memory_mib']) + 'm'
    if 'pids' in changes:
        args[args.index('--pids-limit=32')] = '--pids-limit=' + str(changes['pids'])
    if 'cpus' in changes:
        args[args.index('--cpus=0.5')] = '--cpus=' + str(changes['cpus'])
    if changes.get('nnp') is False:
        args.remove('--security-opt=no-new-privileges')
    for flag in (['--cap-add=' + x for x in changes.get('cap_add', [])] +
                 (['--security-opt=seccomp=unconfined'] if changes.get('seccomp') is False else [])):
        args.insert(args.index(container.IMAGE), flag)
    require(set(changes) <= {'user','network','log','readonly','tmpfs','nofile','nnp','seccomp','cap_add',*resource_controls}, 'unknown test override')
    return args


def verify_policy(data, timeout_s, changes):
    """Verify the declared baseline deviations and every unchanged production check.

    Raw readbacks are retained. Normalizing a copy here does not claim that a
    deliberately relaxed baseline passed production policy.
    """
    for key, allowed in {'memory_mib':(192,), 'pids':(48,), 'cpus':(1,)}.items():
        if key in changes:
            require(type(changes[key]) is int and changes[key] in allowed, 'invalid bounded resource control: ' + key)
    normalized = copy.deepcopy(data)
    c, h = normalized['Config'], normalized['HostConfig']
    for key, value, actual in [('user', changes.get('user','10000:10000'), c['User']),
                              ('network', changes.get('network','none'), h['NetworkMode']),
                              ('log', changes.get('log','none'), h['LogConfig']['Type']),
                              ('readonly', changes.get('readonly',True), h['ReadonlyRootfs']),
                              ('tmpfs', {'/tmp':changes.get('tmpfs',container.TMPFS)}, h['Tmpfs'])]:
        require(value == actual, 'unexpected actual ' + key + ' policy')
    canonical=lambda caps:sorted('CAP_'+name.removeprefix('CAP_') for name in caps)
    require(canonical(h.get('CapAdd') or []) == canonical(changes.get('cap_add', [])), 'unexpected added capabilities')
    security = set(h.get('SecurityOpt') or [])
    nnp = bool(security & {'no-new-privileges','no-new-privileges:true'})
    require(nnp == changes.get('nnp',True), 'unexpected no-new-privileges option')
    security -= {'no-new-privileges','no-new-privileges:true'}
    require(security == ({'seccomp=unconfined'} if changes.get('seccomp') is False else set()), 'unexpected seccomp/security option')
    n = changes.get('nofile',128)
    require(h['Ulimits'] == [dict(Name='nofile',Soft=n,Hard=n)], 'unexpected descriptor limit')
    for key, expected in [('Memory', changes.get('memory_mib',128)*1048576),
                          ('MemorySwap', changes.get('memory_mib',128)*1048576),
                          ('PidsLimit', changes.get('pids',32)), ('NanoCpus', int(changes.get('cpus',0.5)*1000000000))]:
        require(h[key] == expected, 'unexpected actual ' + key + ' policy')
    c['User'] = '10000:10000'
    h.update(NetworkMode='none', ReadonlyRootfs=True, Tmpfs={'/tmp':container.TMPFS},
             CapAdd=None, SecurityOpt=['no-new-privileges'], Ulimits=[dict(Name='nofile',Soft=128,Hard=128)],
             Memory=134217728, MemorySwap=134217728, PidsLimit=32, NanoCpus=500000000)
    h['LogConfig']['Type'] = 'none'
    container._check_policy(normalized, timeout_s)


class Runtime:
    def __init__(self, evidence, main, recovery_records=None):
        os.umask(0o077)
        evidence.mkdir(mode=0o700)
        self.evidence, self.main = evidence, main
        self.deadline = time.monotonic() + 1200
        self.started = self.stopping = False
        self.records, self.networks = [], []
        self.recovery_records = recovery_records or []
        self.admission = None
        self.admitted = False
        self.log_lock = threading.Lock()
        old = Path.home()/'.capy/work/pybox-step4-design/continuation-01/runtime_checks.py'
        shutil.copyfile(old, evidence/'runtime_checks.py')
        spec = importlib.util.spec_from_file_location('m3b_runtime_checks', evidence/'runtime_checks.py')
        self.checks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.checks)
        self.a = self.checks.a
        self.a.run = self.adapter
        self.capture_sequence = 0
        self.inspection_sequence = 0

    def command(self, label, argv, timeout=2, runtime=False, allowed=(0,), source=None, cap=65536):
        if runtime:
            self.a.guard()
        left = self.deadline - time.monotonic() - (0 if self.stopping else 170)
        require(left > 0, 'reserved stop budget reached')
        with self.log_lock:
            self.capture_sequence += 1
            name = '%04d-%s' % (self.capture_sequence, label)
            with (self.evidence/'commands.jsonl').open('a') as file:
                file.write(json.dumps(dict(event='begin',label=name,argv=argv,utc=stamp()))+'\n')
        result = container._capture(argv,input_data=source,timeout_s=min(left,timeout),cap=cap,deadline=self.deadline)
        save(self.evidence/(name+'.command.json'), result)
        with self.log_lock:
            with (self.evidence/'commands.jsonl').open('a') as file:
                file.write(json.dumps(dict(event='end',label=name,argv=argv,utc=stamp(),returncode=result['returncode']))+'\n')
        require(not result['timed_out'] and result['input_complete'] and result['output_complete']
                and result['returncode'] in allowed, name+' command failed: '+str(result['returncode'])+' '+result['stderr'][-1000:])
        if cap == 65536:
            require(not result['stdout_truncated'] and not result['stderr_truncated'], 'incomplete control capture')
        return result

    def adapter(self,label,argv,timeout=30,runtime=False,allowed=(0,)):
        r=self.command(label,argv,timeout,runtime,allowed)
        (self.evidence/(label+'.stdout.txt')).write_text(r['stdout'])
        (self.evidence/(label+'.stderr.txt')).write_text(r['stderr'])
        return r['stdout'],r['stderr'],r['returncode']

    def engine(self,label,args,timeout=2,allowed=(0,),source=None,cap=65536):
        self.checks.endpoint_guard()
        container._guard()
        return self.command(label,container.PREFIX+args,timeout,True,allowed,source,cap)

    def preflight(self):
        require(os.uname().sysname=='Darwin' and os.uname().machine=='arm64' and os.getuid()==501, 'not approved Mac')
        require((self.main/'pybox/container.py').is_file(), 'not a PyBox checkout')
        self.a.guard()
        require(hashlib.sha256(container.OWNER_FILE.read_bytes()).hexdigest()=='f4a163416d814baa68755a9bbf76fa23c89009f4a3edb107e85bf4b2c4bfa64f','installation identity changed')
        profiles=[json.loads(x) for x in self.adapter('initial-vm-state',[self.a.COLIMA,'list','--json'],runtime=True)[0].splitlines() if x.strip()]
        require(len(profiles)==1 and profiles[0]['name']=='pybox' and profiles[0]['status']=='Stopped','VM not initially stopped')
        self.a.snapshot('before')
        baseline=self.checks.socket_pair('baseline')
        self.started=True
        self.adapter('vm-start',[self.a.COLIMA,'start','pybox','--runtime','docker','--vm-type','vz','--arch','aarch64',
                     '--cpus','2','--memory','2','--disk','20','--root-disk','20','--mount=none','--port-forwarder=none',
                     '--activate=false','--ssh-config=false','--ssh-agent=false','--kubernetes=false','--vz-rosetta=false','--binfmt=false'],600,True)
        first=self.checks.socket_pair('postboot-1'); first_time=time.monotonic()
        management=self.checks.compare('postboot-1-vs-baseline',baseline,first)
        self.checks.policy_and_mounts()
        time.sleep(max(0,first_time+10-time.monotonic()))
        require(self.checks.compare('postboot-2-vs-baseline',baseline,self.checks.socket_pair('postboot-2'))==management,'management endpoint changed')
        self.checks.endpoint_guard(); container._guard()
        require(stat.S_IMODE(container.SOCKET.stat().st_mode)==0o600,'socket not 0600')
        image=self.engine('pinned-local-image',['image','inspect',container.IMAGE,'--format','{{json .RepoDigests}} {{.Id}} {{.Os}}/{{.Architecture}}'])['stdout'].strip()
        digests,offset=json.JSONDecoder().raw_decode(image)
        image_id,platform=image[offset:].strip().split()
        require(container.IMAGE in digests and image_id==container.IMAGE.split('@')[1] and platform=='linux/arm64','pinned cached image mismatch')
        self.owner=container._installation_owner()
        self.admission=container._admission(); self.admission.__enter__()
        self.admitted=True
        old=json.loads((self.main/'evidence/raw/pybox-step4-20261019-implementation-01/outcome.json').read_text())
        self.sentinels=old['retained_sentinels']
        self.initial_ids=set(self.engine('initial-container-ids',['container','ls','--all','--quiet','--no-trunc'])['stdout'].split())
        sentinel_ids={r['container_id'] for r in self.sentinels}
        recover_ids={r['container_id'] for r in self.recovery_records}
        require(self.initial_ids==sentinel_ids | recover_ids,'unexpected existing containers; preserve without reconciliation')
        require(not list(container._attempt_directory().iterdir()),'pending application attempts')
        self.verify_sentinels('initial')
        for rec in self.recovery_records:
            require(rec['identity']['labels']['io.pybox.owner']==self.owner and rec.get('create_attempted')
                    and not rec.get('removed') and re.fullmatch('[0-9a-f]{64}',rec['container_id']), 'invalid recorded fixture recovery')
            if 'cleanup_error' in rec: rec['historical_cleanup_error']=rec.pop('cleanup_error')
            rec['recovered_from_prior_attempt']=True
            self.records.append(rec)
            data=self.inspect(rec,rec['label']+'-recovery-preflight')
            require(data['Config']['Labels'].get('io.pybox.checkpoint')=='m3b-fixture' and data['State']['Status']=='created'
                    and not data['State']['Running'],'recovery is not exact never-started M3b fixture')
            self.cleanup(rec)
        self.initial_ids=sentinel_ids
        return dict(management_endpoint=management,platform=platform,existing_ids=sorted(self.initial_ids))

    def inspect(self,rec,label):
        self.inspection_sequence+=1
        fmt='{"LogPath":{{json .LogPath}},'+container.INSPECT[1:]
        data=json.loads(self.engine(label,['container','inspect','--format',fmt,rec['container_id']])['stdout'])
        require(data['Id']==rec['container_id'] and data['Name']=='/'+rec['identity']['name'] and
                all(data['Config']['Labels'].get(k)==v for k,v in rec['identity']['labels'].items()),'fixture ownership mismatch')
        verify_policy(data,rec.get('timeout_s',2),rec.get('changes',{}))
        save(self.evidence/('%04d-%s.inspect.json' % (self.inspection_sequence,label)),data)
        return data

    def verify_sentinels(self,label):
        for rec in self.sentinels:
            data=self.inspect(rec,label+'-'+rec['label'])
            require(data['State']['Status']=='created' and not data['State']['Running'],'sentinel changed')

    def create(self,label,source,changes=None,timeout_s=2):
        changes=changes or {}
        require(len(source.encode())<=65536,'source too large')
        rec=dict(label=label,identity=container._identity(self.owner),changes=changes,timeout_s=timeout_s,source_sha256=hashlib.sha256(source.encode()).hexdigest())
        self.records.append(rec)
        save(self.evidence/(label+'.identity.json'),rec)
        (self.evidence/(label+'.source.py')).write_text(source)
        rec['create_attempted']=True
        cid=self.engine(label+'-create',create_args(rec['identity'],timeout_s,changes),5)['stdout'].strip()
        require(re.fullmatch('[0-9a-f]{64}',cid),'not a full container ID')
        rec['container_id']=cid
        self.inspect(rec,label+'-created')
        return rec

    def attach(self,rec,source,cap=65536):
        result=self.engine(rec['label']+'-start',['container','start','--attach','--interactive',rec['container_id']],
                           rec['timeout_s']+3,allowed=(0,137),source=source.encode(),cap=cap)
        rec['capture']=result
        rec['terminal']=self.inspect(rec,rec['label']+'-terminal')
        require(rec['terminal']['State']['Status']=='exited' and not rec['terminal']['State']['Running'],'target not stopped')
        require(not rec['terminal']['State']['Error'] and result['returncode']==rec['terminal']['State']['ExitCode'],'engine/attach exit mismatch')
        return result

    def cleanup(self,rec):
        if rec.get('removed') or not rec.get('create_attempted'):
            return
        if not rec.get('container_id'):
            args=['container','ls','--all','--quiet','--no-trunc','--filter','name=^/'+rec['identity']['name']+'$']
            for k,v in rec['identity']['labels'].items(): args+=['--filter','label='+k+'='+v]
            found=self.engine(rec['label']+'-recover',args)['stdout'].strip()
            require(re.fullmatch('[0-9a-f]{64}',found),'create unresolved; no broad cleanup')
            rec['container_id']=found
        data=self.inspect(rec,rec['label']+'-before-remove')
        if data['State']['Running']:
            rec['rescue_kill']=True
            self.engine(rec['label']+'-rescue-kill',['container','kill','--signal=KILL',rec['container_id']])
            data=self.inspect(rec,rec['label']+'-after-rescue')
            require(not data['State']['Running'],'rescue kill failed')
        self.engine(rec['label']+'-remove',['container','rm',rec['container_id']],3)
        require(not self.engine(rec['label']+'-absence',['container','ls','--all','--quiet','--no-trunc','--filter','id='+rec['container_id']])['stdout'].strip(),'fixture remains')
        rec['removed']=True

    def container_kib(self,rec,label):
        self.inspect(rec,label+'-identity')
        path='/var/lib/docker/containers/'+rec['container_id']
        out=self.adapter(label,[self.a.COLIMA,'ssh','--profile','pybox','--','sudo','du','-sk','--',path],5,True)[0]
        parts=out.split()
        require(len(parts)==2 and parts[0].isdigit() and parts[1]==path,'ambiguous container storage size')
        return int(parts[0])

    def finish(self,outcome):
        for rec in self.records:
            try: self.cleanup(rec)
            except Exception as exc: rec['cleanup_error']=str(exc); outcome['passed']=False
        for network in self.networks:
            try:
                data=json.loads(self.engine('network-before-remove',['network','inspect',network['id']])['stdout'])[0]
                require(data['Id']==network['id'] and data['Name']==network['name'] and data['Internal'] is True
                        and all(data['Labels'].get(k)==v for k,v in network['labels'].items()) and not data['Containers'],'network identity/attachments changed')
                self.engine('network-remove',['network','rm',network['id']],3); network['removed']=True
            except Exception as exc: network['cleanup_error']=str(exc); outcome['passed']=False
        if hasattr(self,'initial_ids'):
            try:
                self.verify_sentinels('final')
                ids=set(self.engine('final-container-ids',['container','ls','--all','--quiet','--no-trunc'])['stdout'].split())
                require(ids==self.initial_ids,'final existing container set changed')
                outcome['sentinels_preserved']=sorted(ids)
            except Exception as exc: outcome['preservation_error']=str(exc); outcome['passed']=False
        if self.started:
            self.stopping=True
            try: self.a.stop('owned-stop'); outcome['vm']='Stopped'
            except Exception as exc: outcome['stop_error']=str(exc); outcome['passed']=False
        if self.admitted:
            self.admission.__exit__(None,None,None)
        self.a.snapshot('after')
        before=json.loads((self.evidence/'before-state.json').read_text()) if (self.evidence/'before-state.json').exists() else {}
        after=json.loads((self.evidence/'after-state.json').read_text())
        allocated=lambda state:sum(x.get('allocated',0) for x in state.get('trees',{}).get(str(container.ROOT),[]) if x.get('type')==stat.S_IFREG)
        outcome['allocation']=dict(before=allocated(before),after=allocated(after),delta=allocated(after)-allocated(before))
        outcome['finished_at']=stamp()
        outcome['fixtures']=self.records; outcome['networks']=self.networks
        save(self.evidence/'outcome.json',outcome)
