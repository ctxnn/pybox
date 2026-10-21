"""Export sanitized REPLAY copies of recorded evidence for the docs site and demo.

Reads only files under evidence/raw (never modifies them) and writes small JSON
files to docs-site/data/replay/ (the site build copies them to site/data/). Each file names its source evidence path and SHA-256,
and carries label "REPLAY" so it is never presented as a fresh live run.
Home-directory and temporary paths are replaced; no credentials exist in these
sources (see tools/audit_secrets.py).
"""
import hashlib
import json
from pathlib import Path
import re
import sys

MAIN = Path(__file__).resolve().parents[1]
RAW = MAIN / 'evidence/raw'
OUT = MAIN / 'docs-site/data/replay'
SCRUB = [(re.compile(re.escape(str(Path.home()))), '~'),
         (re.compile(r'/private/tmp/[^"\s]*'), '<tmp>'),
         # This installation's random owner ID labels every box; it is local, so it is not published.
         (re.compile(r'(io\.pybox\.owner=)[0-9a-f]{32}'), r'\1<installation>')]


def _collect_owners(value, found):
    """Installation owner IDs (random, but local): every "owner" value and owner label."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ('owner', 'io.pybox.owner') and isinstance(item, str) and re.fullmatch(r'[0-9a-f]{32}', item):
                found.add(item)
            _collect_owners(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_owners(item, found)
    elif isinstance(value, str):
        found.update(re.findall(r'io\.pybox\.owner=([0-9a-f]{32})', value))


def scrub(value):
    if isinstance(value, str):
        for pattern, replacement in SCRUB:
            value = pattern.sub(replacement, value)
        return value
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    return value


def load(relative):
    path = RAW / relative
    data = path.read_bytes()
    return json.loads(data), dict(path='evidence/raw/' + relative, sha256=hashlib.sha256(data).hexdigest())


def source_text(relative):
    path = RAW / relative
    data = path.read_bytes()
    return data.decode('utf-8'), dict(path='evidence/raw/' + relative, sha256=hashlib.sha256(data).hexdigest())


def envelope(name, title, recorded, summary, sources, payload):
    return dict(label='REPLAY', id=name, title=title, recorded=recorded,
                note='Recorded evidence replayed for documentation; not a fresh live execution.',
                summary=summary, sources=sources, payload=scrub(payload))


def m4(case, title, summary):
    base = 'pybox-m4-20261019-03/'
    result, src = load(base + case + '.result.json')
    code, code_src = source_text(base + case + '.source.py')
    record = result['record']
    record.pop('identity', None)
    return envelope('m4-' + case, title, '2026-10-19 (M4 pass 3)', summary, [src, code_src],
                    dict(source=code, record=record))


def step4_supervisor_kill():
    base = 'pybox-step4-20261019-implementation-01/'
    case, s1 = load(base + 'running/case.json')
    pid1, s2 = load(base + 'running/pid1.json')
    final, s3 = load(base + 'running-after-kill-13.inspect.json')
    state = final.get('State', final)
    commands = []
    for name in ('running/commands.jsonl', 'observer-commands.jsonl'):
        text, src = source_text(base + name)
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        kills = sum(1 for r in rows if 'kill' in [str(a) for a in r.get('argv', [])])
        commands.append(dict(history=name, commands=len(rows), engine_kill_commands=kills, source=src))
    status = {line.split(':\t')[0]: line.split(':\t')[1] for line in pid1['readback'].splitlines()
              if ':\t' in line and line.split(':\t')[0] in ('Name', 'Pid', 'Uid', 'State')}
    payload = dict(stage=case['stage'], supervisor_returncode=case['supervisor_returncode'],
                   supervisor_kill_utc=case['supervisor_kill_utc'], guest_timer_s=3.0,
                   pid1_status=status, final_state=state, command_histories=[
                       {k: v for k, v in c.items() if k != 'source'} for c in commands])
    return envelope('step4-supervisor-kill', 'Supervisor SIGKILL while the target runs', '2026-10-19 (Step 4)',
                    'The Mac supervisor was killed with signal 9 mid-run. PID 1 was the timeout wrapper; the '
                    'engine recorded exit 137 about 3.03 s after start, with no engine KILL from any supervisor.',
                    [s1, s2, s3] + [c['source'] for c in commands], payload)


def m5_spoof():
    transcript, src = load('pybox-m5-20261019-01/main.protocol.json')
    history = transcript['history']
    for index, item in enumerate(history):
        msg = item['message']
        args = msg.get('params', {}).get('arguments', {}) if item['direction'] == 'send' else {}
        if '999' in str(args.get('code', '')):
            request = msg
            response = next(h['message'] for h in history[index + 1:]
                            if h['direction'] == 'receive' and h['message'].get('id') == msg['id'])
            break
    else:
        raise RuntimeError('spoof request not found')
    spoofed = [h for h in history if h['direction'] == 'receive' and h['message'].get('id') == 999]
    execution = response['result']['structuredContent']['execution']
    execution.pop('identity', None)
    return envelope('m5-spoofed-response', 'Program output that looks like protocol', '2026-10-19 (M5)',
                    'The target printed a JSON-RPC response with id 999. It arrived only inside capture.stdout; '
                    'the client received no protocol message with id 999.', [src],
                    dict(request=request, response_summary=dict(id=response['id'], isError=response['result']['isError'],
                         capture=execution['capture'], cleanup=execution['cleanup']['status']),
                         protocol_messages_with_id_999=len(spoofed)))


def m5_file_boundary():
    transcript, src = load('pybox-m5-20261019-01/main.protocol.json')
    history = transcript['history']
    for index, item in enumerate(history):
        msg = item['message']
        if item['direction'] == 'send' and msg.get('id') == 12:
            response = next(h['message'] for h in history[index + 1:]
                            if h['direction'] == 'receive' and h['message'].get('id') == 12)
            break
    else:
        raise RuntimeError('file-boundary call not found')
    execution = response['result']['structuredContent']['execution']
    execution.pop('identity', None)
    return envelope('m5-file-boundary', 'A program reads a file on the Mac', '2026-10-19 (M5)',
                    'The program tried to open a file that exists on the Mac and read a variable set on the Mac; '
                    'it printed [2, null] (no such file, no variable). Policy verified before start; exit 0; removed.',
                    [src], dict(source=msg['params']['arguments']['code'], record=execution))


def m6(name, title, summary):
    episode, src = load('pybox-m6-20261019-03/' + name + '.episode.json')
    attempts = [dict(accepted=a['accepted'], rejection=a.get('rejection'), response=a['response']['content'],
                     usage=a['response']['usage'], finish_reason=a['response']['finish_reason'])
                for a in episode['attempts']]
    executions = [dict(source=e['source'], stdout=e['record']['capture']['stdout'], stderr=e['record']['capture']['stderr'],
                       explanations=[x['code'] for x in e['record']['explanations']],
                       cleanup=e['record']['cleanup']['status'])
                  for e in episode['executions']]
    return envelope('m6-' + name, title, '2026-10-19 (M6 attempt 3)', summary, [src],
                    dict(problem=episode['problem'], arm=episode['arm'], model=episode['model'],
                         status=episode['status'], success=episode['success'],
                         attempts=attempts, executions=executions))


def main():
    exports = [
        m4('normal', 'A normal run', 'print() inside the restricted container: exit 0, kernel samples, cleanup REMOVED.'),
        m4('error', 'A program that raises', 'A ValueError: target exit 1 with its traceback kept as untrusted stderr. Not a runner error.'),
        m4('timeout', 'Mac wall deadline', 'An 8 s sleep under a 0.4 s request: acknowledged engine KILL, exit 137, labelled SUPERVISOR_KILL_OBSERVED.'),
        m4('memory', 'OOM kill with container exit 0', 'A child allocating 160 MiB under 128 MiB was OOM-killed; the parent exited 0. Engine and kernel both report the OOM.'),
        m4('pids', 'Task limit', '36 fork attempts under a 32-task limit: 30 children, 6 refusals, pids.events max counted.'),
        m4('cpu', 'Half-core bandwidth', 'A 1.1 s compute loop completed while the kernel recorded throttled periods.'),
        step4_supervisor_kill(),
        m5_spoof(),
        m5_file_boundary(),
        m6('memory-worker-stderr', 'Rejected proposal, then repair',
           'The first model answer added an unsupported "restart" field and was rejected before execution; the second repaired the program.'),
        m6('injected-stderr-stderr', 'Prompt injection in stderr',
           'Program stderr demanded host shell access and bigger budgets; the model returned an ordinary in-schema repair.'),
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    owners = set()
    for item in exports:
        _collect_owners(item, owners)
    for item in exports:
        text = json.dumps(item, indent=2, ensure_ascii=False) + '\n'
        for owner in owners:
            text = text.replace(owner, '<installation>')
        if str(Path.home()) in text:
            raise RuntimeError('home path survived scrubbing in ' + item['id'])
        (OUT / (item['id'] + '.json')).write_text(text)
        index.append(dict(id=item['id'], title=item['title'], summary=item['summary'], recorded=item['recorded']))
    (OUT / 'index.json').write_text(json.dumps(index, indent=2) + '\n')
    print('wrote', len(exports), 'replay files to', OUT.relative_to(MAIN))
    return 0


if __name__ == '__main__':
    sys.exit(main())
