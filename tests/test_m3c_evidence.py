"""Counter provenance/completeness regressions; no VM or workload is launched."""
import copy
import unittest

from pybox import container
from tools.m3c_evidence import FILES, parse_observer, summarize
from tools.runtime_validation import create_args, verify_policy


class ResourceEvidenceTests(unittest.TestCase):
    cid='a'*64

    def raw(self):
        lines=['META\tcgroup\t/docker/'+self.cid,'META\tinode\t123','META\tpid\t100',
               'META\tobserver_cgroup\t/observer','META\tcmdline\ttimeout|-s|KILL|8|python|-I|-B|-u|-|',
               'META\tchild_cmdline\tpython|-I|-B|-u|-|']
        for index in range(2):
            lines+=['SAMPLE\t%d\t%d' % (index,10+index)]
            for name in sorted(FILES):
                if name=='memory.peak': lines+=['UNAVAILABLE\t'+name]
                else:
                    value=('usage_usec %d;nr_throttled %d;core_sched.force_idle_usec 0' % (index*100,index) if name=='cpu.stat'
                           else 'oom_kill %d' % index if name.startswith('memory.events')
                           else 'max %d' % index if name=='pids.events'
                           else 'populated 1' if name=='cgroup.events' else '0')
                    lines+=['VALUE\t'+name+'\t'+value]
            lines+=['END']
            if index==0: lines+=['READY']
        return '\n'.join(lines+['STOP\tdisappeared'])+'\n'

    def parse(self,raw):
        return parse_observer(raw,self.cid,100,8)

    def test_missing_counter_stays_unknown_and_live_observations_are_not_final(self):
        parsed=self.parse(self.raw())
        self.assertFalse(parsed['final_counters_complete'])
        result=summarize(parsed)
        self.assertIsNone(result['memory.peak'])
        self.assertEqual(result['memory.events']['delta']['oom_kill'],1)
        self.assertIn('memory.peak',result['unavailable'])

    def test_incomplete_forged_and_wrong_identity_observations_fail_closed(self):
        raw=self.raw()
        for changed in [raw.replace('END\nSTOP','STOP'),raw.replace('STOP\tdisappeared','STOP\tbudget'),
                        raw.replace('/docker/'+self.cid,'/docker/'+'b'*64),raw.replace('KILL|8|','KILL|9|'),
                        raw.replace('usage_usec 100','usage_usec 100\tforged'),
                        raw.replace('READY\n',''),raw+'TARGET OUTPUT\n']:
            with self.subTest(raw=changed),self.assertRaises(RuntimeError): self.parse(changed)

    def test_counter_reversal_is_not_reported_as_a_valid_delta(self):
        raw=self.raw().replace('usage_usec 0','usage_usec 200')
        with self.assertRaisesRegex(RuntimeError,'counter reversal'): summarize(self.parse(raw))

    def test_only_finite_explicit_resource_controls_are_constructed(self):
        identity=dict(name='test',labels={})
        args=create_args(identity,7,dict(memory_mib=192,pids=48,cpus=1))
        self.assertIn('--memory=192m',args)
        self.assertIn('--memory-swap=192m',args)
        self.assertIn('--pids-limit=48',args)
        self.assertIn('--cpus=1',args)
        for key,value in [('memory_mib',-1),('memory_mib',1024),('pids',-1),('pids',1000),('cpus',0),('cpus',True)]:
            with self.subTest(key=key,value=value),self.assertRaises(RuntimeError): create_args(identity,7,{key:value})

    def test_baseline_does_not_hide_unexpected_memory_swap_task_or_cpu_settings(self):
        data=dict(Config=dict(Image=container.IMAGE,User='10000:10000',Tty=False,OpenStdin=True,Entrypoint=['timeout'],Cmd=container._timer_args(7)),
                  HostConfig=dict(NetworkMode='none',ReadonlyRootfs=True,Privileged=False,Memory=201326592,MemorySwap=201326592,
                    PidsLimit=48,NanoCpus=1000000000,CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
                    Tmpfs={'/tmp':container.TMPFS},LogConfig=dict(Type='none'),Ulimits=[dict(Name='nofile',Hard=128,Soft=128)],
                    RestartPolicy=dict(Name='no')),Mounts=[])
        changes=dict(memory_mib=192,pids=48,cpus=1)
        before=copy.deepcopy(data)
        verify_policy(data,7,changes)
        self.assertEqual(data,before)
        for key in ['Memory','MemorySwap','PidsLimit','NanoCpus']:
            mutated=copy.deepcopy(data); mutated['HostConfig'][key]+=1
            with self.subTest(key=key),self.assertRaisesRegex(RuntimeError,key): verify_policy(mutated,7,changes)
