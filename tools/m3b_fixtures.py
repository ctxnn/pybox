"""Finite known M3b programs; never a validator for arbitrary target output."""
from textwrap import dedent


def source(body, alarm=7):
    return "import signal\nsignal.alarm(%d)\n" % alarm + dedent(body)


FILESYSTEM = source('''
    import errno, json, os
    result = {}
    for label, path in [('root_write', '/var/tmp/pybox-m3b-write')]:
        try:
            with open(path, 'wb') as f: f.write(b'finite probe')
            result[label] = 0
        except OSError as exc: result[label] = exc.errno
    print(json.dumps(result))
''')

SCRATCH = source('''
    import json, os
    total, error = 0, 0
    try:
        with open('/tmp/pybox-scratch', 'wb', buffering=0) as f:
            for _ in range(17):
                block = b'x' * 1048576
                while block:
                    n = f.write(block); total += n; block = block[n:]
    except OSError as exc: error = exc.errno
    print(json.dumps(dict(bytes_written=total, errno=error)))
''')

NOEXEC = source('''
    import json, os, pathlib, subprocess
    p = pathlib.Path('/tmp/pybox-true')
    p.write_bytes(pathlib.Path('/bin/true').read_bytes()); p.chmod(0o700)
    try: result = dict(errno=0, returncode=subprocess.run([str(p)], timeout=1).returncode)
    except OSError as exc: result = dict(errno=exc.errno, returncode=None)
    with open('/proc/self/mounts') as f:
        result['tmp_options'] = next(line.split()[3] for line in f if line.split()[1]=='/tmp')
    print(json.dumps(result))
''')

IDENTITY = source('''
    import json, os
    with open('/proc/self/status') as f:
        status = dict(line.split(':',1) for line in f if ':' in line)
    try: os.listdir('/root'); root_error = 0
    except OSError as exc: root_error = exc.errno
    try: os.setuid(0); setuid_error = 0
    except OSError as exc: setuid_error = exc.errno
    print(json.dumps(dict(uid=os.getuid(), gid=os.getgid(), root_errno=root_error,
                         setuid_errno=setuid_error, cap_eff=status['CapEff'].strip(), cap_bnd=status['CapBnd'].strip())))
''')

CHOWN = source('''
    import json, os
    p = '/tmp/pybox-chown'
    with open(p, 'wb') as f: f.write(b'finite own-file probe')
    try: os.chown(p,10001,10001); error=0
    except OSError as exc: error=exc.errno
    print(json.dumps(dict(uid=os.getuid(), errno=error, file_uid=os.stat(p).st_uid)))
''')

NNP = source('''
    import ctypes as c, json
    lib=c.CDLL(None,use_errno=True)
    before=lib.prctl(39,0,0,0,0)
    c.set_errno(0); clear=lib.prctl(38,0,0,0,0); clear_errno=c.get_errno()
    class Filter(c.Structure):
        _fields_=[('code',c.c_ushort),('jt',c.c_ubyte),('jf',c.c_ubyte),('k',c.c_uint)]
    class Program(c.Structure):
        _fields_=[('length',c.c_ushort),('filter',c.POINTER(Filter))]
    instructions=(Filter*1)(Filter(6,0,0,0x7fff0000))
    program=Program(1,instructions)
    c.set_errno(0); install=lib.prctl(22,2,c.byref(program),0,0); install_errno=c.get_errno()
    print(json.dumps(dict(nnp_before=before,clear_result=clear,clear_errno=clear_errno,
                         nnp_after=lib.prctl(39,0,0,0,0),filter_install=install,filter_errno=install_errno)))
''')

SECCOMP = source('''
    import ctypes as c, json
    lib=c.CDLL(None,use_errno=True)
    c.set_errno(0); result=lib.personality(0x40000); error=c.get_errno()
    with open('/proc/self/status') as f:
        status=dict(line.split(':',1) for line in f if ':' in line)
    print(json.dumps(dict(result=result,errno=error,seccomp=status['Seccomp'].strip())))
''')

DESCRIPTORS = source('''
    import json, os, resource
    descriptors=[]; error=0
    try:
        for _ in range(256): descriptors.append(os.open('/dev/null',os.O_RDONLY))
    except OSError as exc: error=exc.errno
    for fd in descriptors: os.close(fd)
    try: resource.setrlimit(resource.RLIMIT_NOFILE,(256,256)); raised=True
    except (OSError,ValueError): raised=False
    print(json.dumps(dict(limits=resource.getrlimit(resource.RLIMIT_NOFILE),opened=len(descriptors),errno=error,raised=raised)))
''')

FLOOD = source('''
    import os
    for _ in range(64):
        os.write(1,b'x'*4096); os.write(2,b'y'*4096)
''')


def pid1_signal(name):
    if name not in ('SIGTERM', 'SIGSTOP'):
        raise ValueError('only the two planned PID 1 interference probes')
    return source('''
        import json, os, signal, time
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        time.sleep(0.15)
        os.kill(1,signal.%s)
        print(json.dumps(dict(signal='%s',kill_returned=True)),flush=True)
        time.sleep(8)
    ''' % (name,name), alarm=9)


def host_boundary(path):
    return source('''
        import json, os
        with open('/etc/os-release','rb') as f: image_readable=bool(f.read(128))
        try:
            with open(%r,'rb') as f: f.read(128)
            error=0
        except OSError as exc: error=exc.errno
        print(json.dumps(dict(host_errno=error,image_readable=image_readable,
                             canary_env=os.getenv('PYBOX_M3B_HOST_CANARY'))))
    ''' % str(path))


SERVER = source('''
    import json, select, socket, time
    tcp=socket.socket(); tcp.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    tcp.bind(('0.0.0.0',32123)); tcp.listen(1)
    udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); udp.bind(('0.0.0.0',10053))
    seen=set(); deadline=time.monotonic()+5
    while len(seen)<2 and time.monotonic()<deadline:
        for s in select.select([tcp,udp],[],[],0.1)[0]:
            if s is tcp:
                connection,_=tcp.accept(); connection.sendall(b'pybox-finite-canary'); connection.close(); seen.add('tcp')
            else:
                data,peer=udp.recvfrom(512)
                udp.sendto(data[:2]+b'\\x81\\x83'+data[4:],peer); seen.add('dns')
    tcp.close(); udp.close()
    print(json.dumps(dict(seen=sorted(seen))))
''')


def network_probe(address):
    return source('''
        import errno, json, socket
        result={}
        with socket.socket() as s:
            s.settimeout(0.5)
            try:
                s.connect((%r,32123)); result['tcp_reply']=s.recv(64).decode(); result['tcp_errno']=0
            except OSError as exc:
                result['tcp_errno']=exc.errno; result['tcp_error_name']=errno.errorcode.get(exc.errno)
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            # One fixed .invalid DNS query to a private fixture resolver, no Internet.
            query=b'\\x12\\x34\\x01\\x00\\x00\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x05pybox\\x07invalid\\x00\\x00\\x01\\x00\\x01'
            try:
                s.sendto(query,(%r,10053)); reply,_=s.recvfrom(512)
                result['dns_nxdomain']=reply[:2]==query[:2] and reply[3]&15==3; result['dns_errno']=0
            except OSError as exc:
                result['dns_errno']=exc.errno; result['dns_error_name']=errno.errorcode.get(exc.errno)
        print(json.dumps(result))
    ''' % (address,address))


def network_gate(protected, baseline):
    # errno numbers belong to the guest ABI, not to the Mac running this test.
    return (protected.get('tcp_error_name')=='ENETUNREACH' and protected.get('dns_error_name')=='ENETUNREACH'
            and baseline.get('tcp_errno')==0 and baseline.get('tcp_reply')=='pybox-finite-canary'
            and baseline.get('dns_errno')==0 and baseline.get('dns_nxdomain') is True)
