"""Regression for guest-vs-host ABI values and explicit baseline capability scope."""
import copy
import unittest

from pybox import container
from tools.m3b_fixtures import network_gate
from tools.runtime_validation import verify_policy


class ValidationPolicyTests(unittest.TestCase):
    def test_linux_network_errors_are_not_compared_with_host_errno_numbers(self):
        protected=dict(tcp_errno=101,dns_errno=101,tcp_error_name='ENETUNREACH',dns_error_name='ENETUNREACH')
        baseline=dict(tcp_errno=0,tcp_reply='pybox-finite-canary',dns_errno=0,dns_nxdomain=True)
        self.assertTrue(network_gate(protected,baseline))
        for mutation in [dict(dns_error_name=None),dict(tcp_error_name='EACCES')]:
            self.assertFalse(network_gate({**protected,**mutation},baseline))
        self.assertFalse(network_gate(protected,{**baseline,'dns_nxdomain':False}))

    def test_baseline_allows_only_declared_canonical_capability(self):
        data=dict(Config=dict(Image=container.IMAGE,User='0:0',Tty=False,OpenStdin=True,Entrypoint=['timeout'],Cmd=container._timer_args(2)),
                  HostConfig=dict(NetworkMode='none',ReadonlyRootfs=True,Privileged=False,Memory=134217728,MemorySwap=134217728,
                    PidsLimit=32,NanoCpus=500000000,CapDrop=['ALL'],CapAdd=['CAP_CHOWN'],SecurityOpt=['no-new-privileges'],
                    Tmpfs={'/tmp':container.TMPFS},LogConfig=dict(Type='none'),Ulimits=[dict(Name='nofile',Hard=128,Soft=128)],
                    RestartPolicy=dict(Name='no')),Mounts=[])
        before=copy.deepcopy(data)
        verify_policy(data,2,dict(user='0:0',cap_add=['CHOWN']))
        self.assertEqual(data,before)
        for cap in ['CAP_SYS_ADMIN','SYS_ADMIN']:
            data['HostConfig']['CapAdd']=[cap]
            with self.assertRaisesRegex(RuntimeError,'added capabilities'):
                verify_policy(data,2,dict(user='0:0',cap_add=['CHOWN']))
