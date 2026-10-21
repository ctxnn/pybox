"""Production observer framing, lifecycle ordering and normalized result evidence."""
from contextlib import nullcontext, redirect_stdout
from dataclasses import replace
import io
import json
import sys
import threading
import unittest
from unittest import mock

from pybox import container, observation
from pybox.__main__ import main
from test_container_lifecycle import Engine


def observer_raw(cid='a'*64):
    lines=['ARMED\t'+cid,'BIND\t/sys/fs/cgroup/docker/'+cid+'\t123\t/observer']
    for i in range(2):
        lines+=['SAMPLE\t%d\t10.%02d' % (i,i)]
        for name in sorted(observation.FILES):
            if name=='memory.peak': lines+=['UNAVAILABLE\t'+name]
            else:
                value=('usage_usec %d;nr_throttled %d;core_sched.force_idle_usec 0' % (i*100,i) if name=='cpu.stat'
                       else 'oom_kill %d' % i if name.startswith('memory.events')
                       else 'max %d' % i if name=='pids.events'
                       else 'populated %d;frozen 0' % (1-i) if name=='cgroup.events'
                       else '50000 100000' if name=='cpu.max' else '0')
                lines+=['VALUE\t'+name+'\t'+value]
        lines+=['END']
    return '\n'.join(lines+['STOP\tdisappeared'])+'\n'


class ObserverTests(unittest.TestCase):
    def test_live_samples_keep_missing_fields_and_final_uncertainty(self):
        result=observation.parse(observer_raw(),'a'*64)
        self.assertEqual(result['status'],'COLLECTED')
        self.assertEqual(result['metrics']['memory.events']['delta']['oom_kill'],1)
        self.assertIsNone(result['metrics']['memory.peak'])
        self.assertFalse(result['final_counters_complete'])
        self.assertIn('memory.peak',result['unavailable'])
        self.assertEqual(observation.parse('ARMED\t'+'a'*64+'\nSTOP\tnot_seen\n','a'*64)['status'],'UNAVAILABLE')

    def test_forged_identity_truncation_and_counter_reversal_are_rejected(self):
        raw=observer_raw()
        mutations=[raw.replace('/docker/'+'a'*64,'/docker/'+'b'*64),raw.replace('\t123\t/observer','\t123\t/docker/'+'a'*64),
                   raw.replace('STOP\tdisappeared',''),raw.replace('END\nSTOP','STOP'),raw+'forged\n',
                   raw.replace('usage_usec 0','usage_usec 200'),raw.replace('usage_usec 100','usage_usec -1'),
                   raw.replace('nr_throttled 1','nr_throttled 1;nr_throttled 1')]
        for value in mutations:
            with self.subTest(value=value),self.assertRaises(ValueError): observation.parse(value,'a'*64)

    def test_capture_delivers_streamed_readiness_and_reaps_cancelled_client(self):
        stop=threading.Event()
        chunks=[]
        def feed(data):
            chunks.append(data)
            if b'ARMED\n' in b''.join(chunks): stop.set()
        result=container._capture([sys.executable,'-I','-B','-u','-c',"import time;print('ARMED');time.sleep(1)"],
                                  timeout_s=2,on_stdout=feed,cancel=stop)
        self.assertTrue(result['cancelled'])
        self.assertEqual(result['returncode'],-9)
        self.assertLess(result['elapsed_s'],0.8)

    def test_observer_arming_is_fragment_safe_and_transport_failure_is_unknown(self):
        control=mock.Mock(cid='a'*64,operations=[],operations_lock=threading.Lock())
        def capture(argv,*args,**kwargs):
            # Direct ssh joins the remote command into one string; colima ssh passes it as arguments.
            self.assertIn('sudo /usr/bin/timeout -s KILL 6 /bin/sh -s -- '+control.cid,' '.join(argv))
            kwargs['on_stdout'](b'ARM')
            kwargs['on_stdout'](('ED\t'+control.cid+'\n').encode())
            return dict(returncode=0,timed_out=False,cancelled=False,input_complete=True,output_complete=True,
                        stdout_truncated=False,stderr_truncated=False,stderr='',stdout=observer_raw())
        with mock.patch.object(container,'_guard'),mock.patch.object(container,'_capture',side_effect=capture):
            observer=container._Observer(control); observer.start(); result=observer.finish()
        self.assertEqual(result['status'],'COLLECTED')
        with mock.patch.object(container,'_capture',return_value=dict(returncode=137,timed_out=False)):
            observer=container._Observer(control); observer._work(b'fixed')
        self.assertEqual(observer.result['status'],'UNAVAILABLE')


class InspectionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.engine=Engine()
        self.observer=mock.Mock()
        self.observer.finish.return_value=observation.parse(observer_raw(),'a'*64)
        for patcher in [mock.patch.object(container,'_guard'),mock.patch.object(container,'_admission',side_effect=nullcontext),
                        mock.patch.object(container,'_reconcile_owned',return_value=container.CleanupResult(complete=True,admission_allowed=True)),
                        mock.patch.object(container,'_save_attempt'),mock.patch.object(container,'_clear_attempt'),
                        mock.patch.object(container,'_installation_owner',return_value='c'*32),mock.patch.object(container,'_check_policy'),
                        mock.patch.object(container,'_capture',side_effect=self.engine),
                        mock.patch.object(container,'_Observer',return_value=self.observer),
                        mock.patch.object(container.uuid,'uuid4',return_value=mock.Mock(hex='b'*32))]:
            patcher.start(); self.addCleanup(patcher.stop)

    def test_collector_arms_before_start_and_finishes_after_cleanup(self):
        self.observer.start.side_effect=lambda: self.assertFalse(self.engine.started)
        self.observer.finish.side_effect=lambda: (self.assertFalse(self.engine.exists) or observation.parse(observer_raw(),'a'*64))
        result=container.run_container("print('oom_kill 999')")
        record=result.record
        self.assertEqual(record['schema_version'],1)
        self.assertEqual(record['configured']['memory_bytes'],134217728)
        self.assertTrue(record['observed']['policy_verified_before_start'])
        self.assertEqual(record['observed']['resources']['metrics']['memory.events']['last']['oom_kill'],1)
        self.assertEqual(record['cleanup']['status'],'REMOVED')
        self.assertNotIn('operations',record['cleanup']['reconciliation'])
        self.assertEqual(record['clock_domains']['utc_alignment'],'unmeasured')
        self.assertIn('OOM_KILL_COUNTER_OBSERVED',[r['code'] for r in record['explanations']])
        json.dumps(record)

    def test_arming_failure_prevents_source_start_but_still_cleans_up(self):
        self.observer.start.side_effect=RuntimeError('not armed')
        result=container.run_container('pass')
        self.assertFalse(self.engine.started)
        self.assertTrue(result.removed)
        self.assertEqual(result.record['lifecycle']['last_phase'],'collector_arm')
        self.observer.finish.assert_called_once()

    def test_policy_failure_never_launches_collector_or_target(self):
        with mock.patch.object(container,'_check_policy',side_effect=RuntimeError('policy rejected')):
            result=container.run_container('pass')
        self.assertFalse(self.engine.started)
        self.observer.start.assert_not_called()
        self.assertFalse(result.record['observed']['policy_verified_before_start'])

    def test_cancellation_kills_and_removes_target_before_collector_wait(self):
        def capture(argv,*args,**kwargs):
            if argv[len(container.PREFIX):][:2]==['container','start']:
                self.engine.started=self.engine.running=True
                raise KeyboardInterrupt()
            return self.engine(argv,*args,**kwargs)
        with mock.patch.object(container,'_capture',side_effect=capture): result=container.run_container('pass')
        self.assertTrue(result.cancelled)
        self.assertTrue(result.removed)
        self.assertIn('CANCELLED',[r['code'] for r in result.record['explanations']])
        self.assertTrue(any(o['phase']=='kill' for o in result.operations))
        self.observer.finish.assert_called_once()

    def test_counter_failure_does_not_turn_a_successful_target_into_timeout(self):
        self.observer.finish.return_value=observation.unknown('collector transport lost')
        result=container.run_container('pass')
        self.assertFalse(result.timed_out)
        self.assertIsNone(result.runner_error)
        self.assertEqual(result.returncode,0)
        self.assertEqual(result.record['observed']['resources']['status'],'UNAVAILABLE')

    def test_returned_operations_are_a_snapshot_even_if_collector_finishes_late(self):
        result=container.run_container('pass')
        owned=container._Observer.call_args.args[0]
        before=json.dumps(result.operations,sort_keys=True)
        owned.operations[-1]['stdout']='late collector mutation'
        self.assertEqual(json.dumps(result.operations,sort_keys=True),before)

    def test_cli_inspection_is_json_and_reports_cancellation_status(self):
        result=container.run_container('pass')
        stream=io.StringIO()
        with mock.patch('pybox.__main__.run_container',return_value=replace(result,cancelled=True)),\
             mock.patch('sys.stdin',mock.Mock(buffer=io.BytesIO(b'pass'))),redirect_stdout(stream):
            code=main(['container','--inspect','--timeout','0.5'])
        self.assertEqual(code,130)
        self.assertEqual(json.loads(stream.getvalue())['schema_version'],1)
