"""Fixed finite resource fixtures. Importing this file executes no workload."""
import textwrap


def source(body, before=''):
    return '''import os, signal, time, json
signal.alarm(10)
''' + before + '''
ready_end = time.monotonic() + 4
for _ in range(400):
    if os.path.exists('/tmp/pybox-m3c-observer-ready'):
        break
    if time.monotonic() >= ready_end:
        raise RuntimeError('trusted observer not ready')
    time.sleep(0.01)
else:
    raise RuntimeError('trusted observer readiness cap')
''' + textwrap.dedent(body)


MEMORY = source('''
pid = os.fork()
if pid == 0:
    with open('/proc/self/oom_score_adj','w') as f: f.write('1000')
    blocks = []
    for _ in range(160):
        blocks.append(bytearray(1048576))
        time.sleep(0.003)
    time.sleep(0.4)
    os._exit(0)
_, status = os.waitpid(pid,0)
print(json.dumps(dict(child_exit=os.waitstatus_to_exitcode(status))))
time.sleep(0.8)
''')


PROCESSES = source('''
import errno
children, failures = [], []
for _ in range(36):
    try: pid = os.fork()
    except OSError as e:
        failures.append(errno.errorcode.get(e.errno))
        continue
    if pid == 0:
        time.sleep(1.5)
        os._exit(0)
    children.append(pid)
time.sleep(0.7)
for pid in children: os.waitpid(pid,0)
print(json.dumps(dict(created=len(children),failures=failures)))
time.sleep(0.3)
''')


THREADS = source('''
import threading
threading.stack_size(1048576)
release = threading.Event()
threads, failures = [], []
for _ in range(36):
    thread = threading.Thread(target=lambda: release.wait(1.5))
    try: thread.start()
    except RuntimeError as e:
        failures.append(str(e))
        continue
    threads.append(thread)
time.sleep(0.8)
release.set()
for thread in threads: thread.join(2)
print(json.dumps(dict(created=len(threads),failures=failures)))
time.sleep(0.3)
''')


def cpu(seconds=2):
    return source('''
cpu_before, wall_before = time.process_time(), time.monotonic()
end = wall_before + %r
for i in range(200_000_000):
    if i %% 1000 == 0 and time.monotonic() >= end: break
print(json.dumps(dict(cpu_s=time.process_time()-cpu_before,wall_s=time.monotonic()-wall_before)))
time.sleep(0.8)
''' % seconds)


def rlimit(mode):
    assert mode in ('default','catch','ignore','sleep')
    setup = {
        'default': '',
        'catch': "def handler(signum, frame):\n    print(json.dumps(dict(handled='SIGXCPU')))\n    raise SystemExit(23)\nsignal.signal(signal.SIGXCPU,handler)\n",
        'ignore': 'signal.signal(signal.SIGXCPU,signal.SIG_IGN)\n',
        'sleep': '',
    }[mode]
    work = ("time.sleep(1.3)\nprint(json.dumps(dict(awake=True)))\ntime.sleep(0.3)\n" if mode == 'sleep' else '''
end = time.monotonic()+5.5
for i in range(200_000_000):
    if i % 1000 == 0 and (time.process_time() >= 2.3 or time.monotonic() >= end): break
print(json.dumps(dict(unexpected_survival=True,cpu_s=time.process_time())))
''')
    return source("print(json.dumps(dict(rlimit=[1,2],mode="+repr(mode)+")))\n"+setup+work,
                  before="import resource\nresource.setrlimit(resource.RLIMIT_CORE,(0,0))\nresource.setrlimit(resource.RLIMIT_CPU,(1,2))\n"
                         "assert resource.getrlimit(resource.RLIMIT_CPU)==(1,2)\n")
