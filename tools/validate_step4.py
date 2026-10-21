"""One bounded, local Step 4 acceptance pass. Requires explicit --execute.

Uses the preserved accepted preflight helpers, copied into a fresh evidence
directory. No installs, pulls, config repair, watchdog, or historical log edits.
"""
import argparse
from dataclasses import asdict
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid

MAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MAIN))
from pybox import container

OLD_CHECKS = Path.home()/'.capy/work/pybox-step4-design/continuation-01/runtime_checks.py'
SOURCE = 'import time; print("supervisor-fixture-started", flush=True); time.sleep(8)\n'


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def save(path, data):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def event(path, data):
    with path.open('a') as file:
        file.write(json.dumps(data) + '\n')


def require(value, reason):
    if not value:
        raise RuntimeError(reason)


def child(mode, evidence):
    """Disposable actual supervisor. Only these finite observation hooks differ."""
    signal.alarm(15)
    capture = container._capture
    check = container._check_policy
    read = os.read
    created = {}

    def ready(stage):
        records = [container._read_attempt(p) for p in container._attempt_directory().iterdir()]
        records = [r for r in records if r['identity']['name'] == created['name']]
        require(len(records) == 1, 'expected exactly one supervisor attempt')
        save(evidence / 'ready.json', dict(stage=stage, supervisor_pid=os.getpid(),
             container_id=created['cid'], identity=records[0]['identity'], journal=records[0], utc=stamp()))

    def tracked(argv, *args, **kwargs):
        event(evidence / 'commands.jsonl', dict(event='begin', argv=argv, utc=stamp()))
        result = capture(argv, *args, **kwargs)
        event(evidence / 'commands.jsonl', dict(event='end', argv=argv, utc=stamp(), result=result))
        if argv[len(container.PREFIX):len(container.PREFIX) + 2] == ['container', 'create']:
            created['cid'] = result['stdout'].strip()
            created['name'] = argv[argv.index('--name') + 1]
            if mode == 'before_ack':
                ready('created_before_acknowledgement')
                time.sleep(10)
        return result

    def policy(data, timeout_s=2):
        check(data, timeout_s)
        if mode == 'before_start' and data['State']['Status'] == 'created':
            ready('acknowledged_create_before_start')
            time.sleep(10)

    def observed_read(fd, count):
        data = read(fd, count)
        if mode == 'running' and b'supervisor-fixture-started\n' in data:
            # This is readiness only; engine/proc records establish PID/termination.
            ready('source_executed_and_output_read')
        return data

    container._capture = tracked
    container._check_policy = policy
    os.read = observed_read
    result = container.run_container(SOURCE)
    save(evidence / 'unexpected-supervisor-result.json', asdict(result))
    raise RuntimeError('supervisor returned instead of being SIGKILLed')


def execute(evidence):
    os.umask(0o077)
    evidence.mkdir(mode=0o700)  # Never overwrite an earlier pass.
    shutil.copyfile(OLD_CHECKS, evidence / 'runtime_checks.py')
    spec = importlib.util.spec_from_file_location('step4_live_checks', evidence / 'runtime_checks.py')
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    a = checks.a
    outer_deadline = time.monotonic() + 1200
    outcome = dict(passed=False, started_at=stamp(), evidence=str(evidence), cases=[], retained_sentinels=[])
    records, supervisors = [], []
    owner = None
    started = False
    stopping = False
    original_capture = container._capture

    def capture(label, argv, timeout=2, runtime=False, allowed=(0,), input_data=None):
        if runtime:
            a.guard()
        remaining = outer_deadline - time.monotonic() - (0 if stopping else 170)
        require(remaining > 0, 'whole-pass budget exhausted; stop reserve retained')
        event(evidence / 'observer-commands.jsonl', dict(event='begin', label=label, argv=argv, utc=stamp()))
        result = original_capture(argv, input_data=input_data, timeout_s=min(timeout, remaining), deadline=outer_deadline)
        save(evidence / (label + '.command.json'), result)
        event(evidence / 'observer-commands.jsonl', dict(event='end', label=label, argv=argv, utc=stamp(),
                                                       returncode=result['returncode'], timed_out=result['timed_out']))
        require(not result['timed_out'] and result['output_complete'] and result['input_complete']
                and not result['stdout_truncated'] and not result['stderr_truncated'] and result['returncode'] in allowed,
                label + ' failed: ' + str(result['returncode']) + ' ' + result['stderr'][-1500:])
        return result

    def adapter(label, argv, timeout=30, runtime=False, allowed=(0,)):
        result = capture(label, argv, timeout, runtime, allowed)
        (evidence / (label + '.stdout.txt')).write_text(result['stdout'])
        (evidence / (label + '.stderr.txt')).write_text(result['stderr'])
        return result['stdout'], result['stderr'], result['returncode']

    a.run = adapter

    def engine(label, args, timeout=2, allowed=(0,)):
        checks.endpoint_guard()
        container._guard()
        return capture(label, container.PREFIX + args, timeout, True, allowed)

    def production_capture(argv, *args, **kwargs):
        event(evidence / 'production-commands.jsonl', dict(event='begin', argv=argv, utc=stamp()))
        result = original_capture(argv, *args, **kwargs)
        event(evidence / 'production-commands.jsonl', dict(event='end', argv=argv, utc=stamp(), result=result))
        return result

    def inspect(rec, label):
        data = json.loads(engine(label, ['container', 'inspect', '--format', container.INSPECT, rec['container_id']])['stdout'])
        require(data['Id'] == rec['container_id'] and data['Name'] == '/' + rec['identity']['name'] and
                all(data['Config']['Labels'].get(k) == v for k, v in rec['identity']['labels'].items()), 'fixture identity mismatch')
        container._check_policy(data, rec.get('timeout_s', 2))
        save(evidence / (label + '.inspect.json'), data)
        return data

    def sentinel(label, sentinel_owner, expiry):
        identity = container._identity(sentinel_owner)
        identity['labels']['io.pybox.expires'] = str(expiry)
        rec = dict(label=label, identity=identity, sentinel=True)
        records.append(rec)
        rec['container_id'] = engine(label + '-create', container._create_args(identity), 5)['stdout'].strip()
        inspect(rec, label + '-created')
        outcome['retained_sentinels'].append(rec)
        return rec

    def verify_sentinels(phase):
        for rec in outcome['retained_sentinels']:
            data = inspect(rec, phase + '-' + rec['label'])
            require(data['State']['Status'] == 'created' and not data['State']['Running'], 'sentinel changed')

    def cli_cleanup(label):
        result = capture(label, [sys.executable, '-B', '-m', 'pybox', 'cleanup'], 20, allowed=(0, 125))
        report = json.loads(result['stdout'])
        save(evidence / (label + '.result.json'), report)
        require(result['returncode'] == 0 and report['complete'] and not report['runner_error'], 'cleanup did not complete')
        return report

    def wait_until(epoch, label):
        while time.time() < epoch:
            require(time.monotonic() < outer_deadline - 170, 'expiry wait exhausted reserved budget')
            save(evidence / 'status.json', dict(phase=label, wait_remaining_s=max(0, epoch - time.time()), utc=stamp()))
            time.sleep(max(0, min(0.5, epoch - time.time())))

    def kill_case(mode):
        folder = evidence / mode
        folder.mkdir(mode=0o700)
        out = (folder / 'supervisor.stdout.txt').open('wb')
        err = (folder / 'supervisor.stderr.txt').open('wb')
        process = subprocess.Popen([sys.executable, '-I', '-B', str(Path(__file__).resolve()),
                                   '--child-mode', mode, '--evidence', str(folder)],
                                   stdin=subprocess.DEVNULL, stdout=out, stderr=err, cwd=MAIN,
                                   env=dict(container.ENV), start_new_session=True, close_fds=True)
        supervisors.append((process, out, err))
        end = time.monotonic() + 2.5
        while not (folder / 'ready.json').exists() and process.poll() is None and time.monotonic() < end:
            time.sleep(0.02)
        require((folder / 'ready.json').exists(), mode + ' readiness missing; no retry')
        rec = json.loads((folder / 'ready.json').read_text())
        rec.update(label=mode, sentinel=False)
        records.append(rec)
        data = inspect(rec, mode + '-before-supervisor-kill')
        if mode == 'running':
            require(data['State']['Running'], 'target not running before supervisor kill')
            proc = engine(mode + '-actual-pid1', ['container', 'exec', rec['container_id'], '/bin/cat',
                                                '/proc/1/status', '/proc/1/cmdline'])['stdout']
            save(folder / 'pid1.json', dict(readback=proc))
            require('Name:\ttimeout\n' in proc and 'Pid:\t1\n' in proc and 'PPid:\t0\n' in proc
                    and 'timeout\x00-s\x00KILL\x003\x00python\x00-I\x00-B\x00-u\x00-\x00' in proc,
                    'actual PID 1 not expected timer')
        else:
            require(data['State']['Status'] == 'created' and not data['State']['Running'], 'before-start fixture started')
        rec['supervisor_kill_utc'] = stamp()
        process.kill()  # Exact acquired supervisor handle, never its process group.
        rec['supervisor_returncode'] = process.wait(timeout=2)
        require(rec['supervisor_returncode'] == -signal.SIGKILL, 'supervisor was not SIGKILLed')
        out.close()
        err.close()
        rec['supervisor_died'] = True
        if mode == 'running':
            end = time.monotonic() + 5
            count = 0
            while time.monotonic() < end:
                data = inspect(rec, mode + '-after-kill-' + str(count))
                count += 1
                if not data['State']['Running']:
                    break
                time.sleep(0.2)
            state = data['State']
            life = (datetime.datetime.fromisoformat(state['FinishedAt'].replace('Z', '+00:00')) -
                    datetime.datetime.fromisoformat(state['StartedAt'].replace('Z', '+00:00'))).total_seconds()
            require(state['Status'] == 'exited' and not state['Running'] and state['ExitCode'] == 137
                    and not state['OOMKilled'] and not state['Error'] and 2.8 <= life < 4.5,
                    'guest timer deadline failed; natural 8s exit cannot pass')
            rec['target_lifetime_s'] = life
            rec['termination_evidence'] = container._termination_evidence(data, [], 3)
        else:
            data = inspect(rec, mode + '-after-supervisor-kill')
            require(data['State']['Status'] == 'created' and data['State']['StartedAt'].startswith('0001-'), 'never-started state lost')
        rec['retained_after_death'] = True
        rec['terminal_state'] = data['State']
        commands = [json.loads(line) for line in (folder / 'commands.jsonl').read_text().splitlines()]
        require(not any(x['argv'][len(container.PREFIX):len(container.PREFIX) + 2] == ['container', 'kill'] for x in commands),
                'dead supervisor issued an engine KILL')
        rec['child_engine_kill_commands'] = 0
        outcome['cases'].append(rec)
        save(folder / 'case.json', rec)
        return rec

    try:
        require(os.uname().sysname == 'Darwin' and os.uname().machine == 'arm64' and os.getuid() == 501, 'not approved Mac/UID')
        require((MAIN / 'pybox/container.py').is_file(), 'not a PyBox checkout')
        for ref, expected in [('HEAD', '1e07a74c7fe202c89fc11143a66db7a5b84efe9e'),
                              ('refs/heads/main', '262096c3e49a8332650b92c02e5723da9f50a6a3'),
                              ('refs/heads/checkpoint/m3a-step2', '45730cc54d5954b739eb26c6f5e5e7bdc6efb2b9')]:
            require(capture('ref-' + ref.replace('/', '-'), ['/usr/bin/git', '-C', str(MAIN), 'rev-parse', ref], 5)['stdout'].strip() == expected, 'baseline ref changed')
        source_hashes = {str(p.relative_to(MAIN)): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                         list((MAIN / 'pybox').glob('*.py')) + list((MAIN / 'tests').glob('*.py')) + [Path(__file__).resolve()]}
        save(evidence / 'validated-source-hashes.json', source_hashes)
        a.guard()
        require(hashlib.sha256(container.OWNER_FILE.read_bytes()).hexdigest() == 'f4a163416d814baa68755a9bbf76fa23c89009f4a3edb107e85bf4b2c4bfa64f', 'installation identity changed')
        profiles = [json.loads(x) for x in adapter('initial-vm-state', [a.COLIMA, 'list', '--json'], runtime=True)[0].splitlines() if x.strip()]
        require(len(profiles) == 1 and profiles[0]['name'] == 'pybox' and profiles[0]['status'] == 'Stopped', 'dedicated VM not initially stopped')
        a.snapshot('before')
        baseline = checks.socket_pair('baseline')
        started = True
        adapter('vm-start', [a.COLIMA, 'start', 'pybox', '--runtime', 'docker', '--vm-type', 'vz', '--arch', 'aarch64',
                            '--cpus', '2', '--memory', '2', '--disk', '20', '--root-disk', '20', '--mount=none',
                            '--port-forwarder=none', '--activate=false', '--ssh-config=false', '--ssh-agent=false',
                            '--kubernetes=false', '--vz-rosetta=false', '--binfmt=false'], 600, runtime=True)
        first = checks.socket_pair('postboot-1')
        first_time = time.monotonic()
        management = checks.compare('postboot-1-vs-baseline', baseline, first)
        checks.policy_and_mounts()
        time.sleep(max(0, first_time + 10 - time.monotonic()))
        require(checks.compare('postboot-2-vs-baseline', baseline, checks.socket_pair('postboot-2')) == management, 'management endpoint changed')
        checks.endpoint_guard()
        container._guard()
        require(stat.S_IMODE(container.SOCKET.stat().st_mode) == 0o600, 'socket not 0600')
        image = engine('local-pinned-image', ['image', 'inspect', container.IMAGE, '--format', '{{json .RepoDigests}} {{.Id}} {{.Os}}/{{.Architecture}}'])['stdout'].strip()
        digests, offset = json.JSONDecoder().raw_decode(image)
        image_id, platform = image[offset:].strip().split()
        require(container.IMAGE in digests and image_id == container.IMAGE.split('@')[1] and platform == 'linux/arm64', 'pinned cached image changed')
        owner = container._installation_owner()
        require(not engine('initial-all-containers', ['container', 'ls', '--all', '--quiet', '--no-trunc'])['stdout'].strip(), 'preexisting containers; no fixture admission')
        require(not list(container._attempt_directory().iterdir()), 'preexisting pending attempts; no fixture admission')
        outcome['gates_passed'] = True
        outcome['management_endpoint'] = management
        sentinel('foreign-sentinel', uuid.uuid4().hex, int(time.time()) - 1)
        sentinel('unexpired-sentinel', owner, int(time.time()) + 600)
        container._capture = production_capture
        primary = container.run_container(SOURCE, timeout_s=0.5)
        save(evidence / 'primary-wall.result.json', asdict(primary))
        require(primary.timed_out and primary.returncode == 137 and primary.cleanup_status == 'REMOVED'
                and primary.runner_error is None and primary.termination_evidence['mechanism'] == 'SUPERVISOR_KILL_OBSERVED',
                'primary Mac deadline/engine KILL path failed')
        outcome['primary_wall'] = asdict(primary)
        running = kill_case('running')
        # Keep expiry windows separated so both automatic and manual removal are
        # exercised against real expiry without clock/production-policy changes.
        wait_until(int(running['identity']['labels']['io.pybox.expires']) - container.EXPIRY_S + 8, 'spacing-created-cases')
        before_start = kill_case('before_start')
        before_ack = kill_case('before_ack')
        early = cli_cleanup('before-expiry-cleanup')
        require(not early['removed'] and len(early['found']) == 4 and all(x['status'] == 'KEPT_UNEXPIRED' for x in early['found']),
                'unexpired leftover was hidden or removed')
        verify_sentinels('before-expiry')
        wait_until(int(running['identity']['labels']['io.pybox.expires']) + 0.1, 'waiting-running-expiry')
        fresh = container.run_container('print("fresh-after-reconciliation")\n')
        save(evidence / 'fresh-run.result.json', asdict(fresh))
        require(fresh.runner_error is None and fresh.stdout == 'fresh-after-reconciliation\n' and fresh.cleanup_status == 'REMOVED'
                and fresh.reconciliation['removed'] == [running['container_id']], 'fresh-run reconciliation failed')
        running['removed_by'] = 'next_run_reconciliation'
        verify_sentinels('after-fresh-run')
        wait_until(max(int(before_start['identity']['labels']['io.pybox.expires']), int(before_ack['identity']['labels']['io.pybox.expires'])) + 0.1,
                   'waiting-created-expiry')
        manual = cli_cleanup('after-expiry-manual-cleanup')
        require(set(manual['removed']) == {before_start['container_id'], before_ack['container_id']}, 'manual cleanup did not remove both expired created objects')
        before_start['removed_by'] = before_ack['removed_by'] = 'manual_cleanup'
        verify_sentinels('final')
        require(not list(container._attempt_directory().iterdir()), 'attempt records remain after confirmed removal')
        final_ids = set(engine('final-all-containers', ['container', 'ls', '--all', '--quiet', '--no-trunc'])['stdout'].split())
        require(final_ids == {r['container_id'] for r in outcome['retained_sentinels']}, 'unexpected final objects')
        outcome['final_container_ids'] = sorted(final_ids)
        outcome['reconciliation'] = dict(early=early, fresh= fresh.reconciliation, manual=manual)
        observer_events = [json.loads(x) for x in (evidence / 'observer-commands.jsonl').read_text().splitlines()]
        require(not any(x['argv'][len(container.PREFIX):len(container.PREFIX) + 2] == ['container', 'kill'] for x in observer_events),
                'observer rescue kill invalidates timer success')
        outcome['observer_engine_kill_commands'] = 0
        require(all(hashlib.sha256((MAIN / name).read_bytes()).hexdigest() == value for name, value in source_hashes.items()), 'validated source changed during live pass')
        outcome['passed'] = True
    except BaseException as exc:
        outcome['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        container._capture = original_capture
        for process, out, err in supervisors:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)
            out.close()
            err.close()
        if not outcome['passed'] and owner:
            for rec in records:
                if rec.get('sentinel') or not rec.get('container_id'):
                    continue
                try:
                    ids = engine(rec['label'] + '-failure-query', ['container', 'ls', '--all', '--quiet', '--no-trunc', '--filter', 'id=' + rec['container_id']])['stdout'].strip()
                    if not ids:
                        continue
                    data = inspect(rec, rec['label'] + '-failure-inspect')
                    if data['State']['Running']:
                        rec['rescue_kill'] = True
                        engine(rec['label'] + '-rescue-kill', ['container', 'kill', '--signal=KILL', rec['container_id']])
                        inspect(rec, rec['label'] + '-after-rescue')
                    engine(rec['label'] + '-failure-remove', ['container', 'rm', rec['container_id']], 3)
                    container._clear_attempt(rec['identity'])
                except Exception as exc:
                    rec['failure_cleanup_error'] = str(exc)
        if started:
            stopping = True
            try:
                a.stop('owned-stop')
                outcome['vm'] = 'Stopped'
            except BaseException as exc:
                outcome['passed'] = False
                outcome['stop_error'] = str(exc)
        a.snapshot('after')
        before = json.loads((evidence / 'before-state.json').read_text()) if (evidence / 'before-state.json').exists() else {}
        after = json.loads((evidence / 'after-state.json').read_text())
        allocation = lambda data: sum(x.get('allocated', 0) for x in data.get('trees', {}).get(str(container.ROOT), []) if x.get('type') == stat.S_IFREG)
        outcome['runtime_allocation'] = dict(before_bytes=allocation(before), after_bytes=allocation(after),
                                           delta_bytes=allocation(after) - allocation(before), metric='regular-file st_blocks*512; not APFS exclusive')
        outcome['finished_at'] = stamp()
        save(evidence / 'outcome.json', outcome)
        save(evidence / 'status.json', dict(phase='complete', passed=outcome['passed'], vm=outcome.get('vm'), utc=stamp()))
        print(json.dumps({k: outcome.get(k) for k in ['passed', 'error', 'vm', 'evidence', 'observer_engine_kill_commands', 'runtime_allocation']}, indent=2), flush=True)
    return 0 if outcome['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--child-mode', choices=['running', 'before_start', 'before_ack'])
    args = parser.parse_args()
    if args.child_mode:
        child(args.child_mode, args.evidence)
    elif args.execute:
        sys.exit(execute(args.evidence))
    else:
        parser.error('explicit --execute is required')
