"""Bounded live cgroup observations; target output is never an evidence source."""
import re


FILES = frozenset(('cgroup.events','memory.max','memory.swap.max','memory.swap.current','memory.current',
                   'memory.peak','memory.events','memory.events.local','pids.max','pids.current','pids.peak',
                   'pids.events','cpu.max','cpu.max.burst','cpu.stat'))
KEYED = frozenset(('cgroup.events','memory.events','memory.events.local','pids.events','cpu.stat'))


def unknown(reason, *, status='UNAVAILABLE'):
    return dict(status=status,provenance='trusted guest cgroup v2 files over dedicated Colima SSH',
                sample_count=0,metrics={},binding=None,unavailable=sorted(FILES),
                final_counters_complete=False,error=reason)


def _require(condition, message):
    if not condition: raise ValueError(message)


def parse(raw, cid):
    """Accept only complete framed captures and exact full-ID cgroup binding."""
    _require(isinstance(raw,str) and len(raw.encode())<=131072,'observer output exceeds bound')
    _require(re.fullmatch('[0-9a-f]{64}',cid) is not None,'invalid observer container ID')
    lines=raw.splitlines()
    _require(bool(lines) and lines[0]=='ARMED\t'+cid,'observer was not armed for this container')
    binding, samples, current, stopped = None, [], None, None
    for line in lines[1:]:
        parts=line.split('\t'); kind=parts[0]
        _require(stopped is None,'data after observer stop')
        if kind=='BIND':
            _require(binding is None and not samples and current is None and len(parts)==4,'invalid observer binding')
            path,inode,own=parts[1:]
            _require(path in ('/sys/fs/cgroup/docker/'+cid,'/sys/fs/cgroup/system.slice/docker-'+cid+'.scope')
                     and inode.isdigit() and int(inode)>0 and own.startswith('/') and '/sys/fs/cgroup'+own!=path,
                     'observer cgroup identity mismatch')
            binding=dict(path=path,inode=int(inode),observer_cgroup=own,container_id=cid,
                         identity_source='verified engine ID/name/labels before START; exact canonical guest cgroup path/inode')
        elif kind=='SAMPLE':
            _require(binding is not None and current is None and len(parts)==3 and len(samples)<64
                     and parts[1]==str(len(samples)) and re.fullmatch(r'[0-9]+\.[0-9]+',parts[2]),'invalid observer sample')
            current=dict(guest_uptime_s=float(parts[2]),values={},unavailable=[])
        elif kind in ('VALUE','UNAVAILABLE'):
            _require(current is not None and len(parts)==(3 if kind=='VALUE' else 2) and parts[1] in FILES,'invalid counter frame')
            name=parts[1]
            _require(name not in current['values'] and name not in current['unavailable'],'duplicate counter')
            if kind=='UNAVAILABLE': current['unavailable'].append(name)
            else:
                value=parts[2]
                if name in KEYED:
                    rows=value.split(';')
                    _require(all(re.fullmatch(r'[a-z][a-z0-9_.]* [0-9]+',row) for row in rows),'invalid keyed counter')
                    parsed={k:int(v) for k,v in (row.split() for row in rows)}
                    _require(len(parsed)==len(rows),'duplicate counter key')
                else:
                    _require(re.fullmatch(r'(?:[0-9]+|max)(?: [0-9]+)?',value) is not None,'invalid scalar counter')
                    parsed=value if name=='cpu.max' or value=='max' else int(value)
                current['values'][name]=parsed
        elif kind=='END':
            _require(parts==['END'] and current is not None and set(current['values'])|set(current['unavailable'])==FILES,'incomplete sample')
            samples.append(current); current=None
        elif kind=='STOP':
            _require(len(parts)==2 and current is None and parts[1] in ('not_seen','disappeared','unpopulated','sample_cap'),'invalid observer stop')
            stopped=parts[1]
        else: raise ValueError('unrecognized observer frame')
    _require(current is None and stopped is not None,'incomplete observer capture')
    _require((stopped=='not_seen' and binding is None and not samples) or (stopped!='not_seen' and binding is not None),'invalid stop/binding combination')
    if not samples:
        result=unknown('execution cgroup not sampled before it disappeared')
        result.update(binding=binding,stop_reason=stopped)
        return result
    _require(all(a['guest_uptime_s']<=b['guest_uptime_s'] for a,b in zip(samples,samples[1:])),'observer clock reversal')
    metrics={}
    for name in sorted(FILES):
        observed=[s['values'][name] for s in samples if name in s['values']]
        if not observed:
            metrics[name]=None
            continue
        first,last=observed[0],observed[-1]
        item=dict(first=first,last=last,read_count=len(observed),completeness='live samples; final unknown')
        if name in KEYED:
            keys=set(first)
            _require(all(set(v)==keys for v in observed),'counter fields changed during observation')
            if name!='cgroup.events':
                _require(all(a[k]<=b[k] for a,b in zip(observed,observed[1:]) for k in keys),'counter reversal')
                item['delta']={k:last[k]-first[k] for k in keys}
        elif isinstance(first,int): item['max_observed']=max(observed)
        metrics[name]=item
    return dict(status='COLLECTED',provenance='trusted guest cgroup v2 files over dedicated Colima SSH',
                binding=binding,sample_count=len(samples),first_guest_uptime_s=samples[0]['guest_uptime_s'],
                last_guest_uptime_s=samples[-1]['guest_uptime_s'],metrics=metrics,
                unavailable=sorted({f for s in samples for f in s['unavailable']}),stop_reason=stopped,
                final_counters_complete=False,error=None)
