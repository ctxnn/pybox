"""Parse only the trusted observer's framed output, never target stdout."""
import re

from tools.runtime_validation import require

FILES = {'cgroup.events','memory.max','memory.swap.max','memory.swap.current','memory.oom.group',
         'memory.current','memory.peak','memory.events','memory.events.local','pids.max','pids.current',
         'pids.peak','pids.events','cpu.max','cpu.max.burst','cpu.stat'}


def parse_observer(raw, cid, pid, timer):
    metadata, samples, current, ready, stopped = {}, [], None, False, None
    for line in raw.splitlines():
        parts = line.split('\t')
        kind = parts[0]
        if kind == 'META':
            require(len(parts)==3 and parts[1] not in metadata and current is None and not samples,'invalid observer metadata')
            metadata[parts[1]]=parts[2]
        elif kind == 'SAMPLE':
            require(len(parts)==3 and current is None and not stopped and int(parts[1])==len(samples),'invalid observer sequence')
            current=dict(index=int(parts[1]),guest_uptime_s=float(parts[2]),values={},unavailable=[])
        elif kind in ('VALUE','UNAVAILABLE'):
            require(current is not None and len(parts)==(3 if kind=='VALUE' else 2) and parts[1] in FILES,'invalid observer value')
            name=parts[1]
            require(name not in current['values'] and name not in current['unavailable'],'duplicate observer value')
            if kind=='VALUE':
                require(bool(re.fullmatch(r'[a-z0-9_. ;]+',parts[2])),'unexpected counter format')
                current['values'][name]=parts[2]
            else: current['unavailable'].append(name)
        elif kind == 'END':
            require(current is not None and set(current['values'])|set(current['unavailable'])==FILES,'incomplete observer sample')
            samples.append(current); current=None
        elif kind == 'READY':
            require(not ready and len(samples)==1 and current is None,'invalid observer readiness')
            ready=True
        elif kind == 'STOP':
            require(len(parts)==2 and parts[1] in ('disappeared','unpopulated','budget','sample_cap') and not stopped and current is None,'invalid observer stop')
            stopped=parts[1]
        else: raise RuntimeError('unrecognized observer frame')
    require(current is None and ready and samples and stopped in ('disappeared','unpopulated'),'observer incomplete or exceeded budget')
    require(metadata.get('cgroup') in ('/docker/'+cid,'/system.slice/docker-'+cid+'.scope') and metadata.get('pid')==str(pid)
            and metadata.get('inode','').isdigit() and metadata.get('observer_cgroup')!=metadata['cgroup'],'observer identity mismatch')
    require(metadata.get('cmdline')=='timeout|-s|KILL|'+format(timer,'.17g')+'|python|-I|-B|-u|-|'
            and metadata.get('child_cmdline')=='python|-I|-B|-u|-|','unexpected guest processes')
    require(all(a['guest_uptime_s']<=b['guest_uptime_s'] for a,b in zip(samples,samples[1:])),'observer clock reversal')
    return dict(provenance='trusted guest /proc and cgroup v2 files; outside target cgroup',metadata=metadata,samples=samples,
                stop_reason=stopped,final_counters_complete=False,
                limitation='non-atomic live samples; last readable sample is a lower bound, not guaranteed exit counters')


def scalar(value):
    return value if value=='max' else int(value)


def keyed(value):
    return {name:int(count) for name,count in (row.split() for row in value.split(';') if row)}


def summarize(evidence):
    samples=evidence['samples']
    summary=dict(samples=len(samples),observed_span_s=round(samples[-1]['guest_uptime_s']-samples[0]['guest_uptime_s'],3),
                 unavailable=sorted({f for s in samples for f in s['unavailable']}),limits={})
    for name in ['memory.max','memory.swap.max','memory.oom.group','pids.max','cpu.max','cpu.max.burst']:
        vals={s['values'][name] for s in samples if name in s['values']}
        require(len(vals)<=1,'resource configuration changed while observing: '+name)
        summary['limits'][name]=next(iter(vals)) if vals else None
    for name in ['memory.current','memory.peak','memory.swap.current','pids.current','pids.peak']:
        values=[scalar(s['values'][name]) for s in samples if name in s['values']]
        summary[name]=dict(first=values[0],max=max(values),last=values[-1]) if values else None
    for name in ['memory.events','memory.events.local','pids.events','cpu.stat']:
        values=[keyed(s['values'][name]) for s in samples if name in s['values']]
        if not values:
            summary[name]=None
            continue
        keys=set(values[0])
        require(all(set(v)==keys for v in values),'counter keys changed: '+name)
        require(all(a[k]<=b[k] for a,b in zip(values,values[1:]) for k in keys),'counter reversal: '+name)
        summary[name]=dict(first=values[0],last=values[-1],delta={k:values[-1][k]-values[0][k] for k in keys})
    return summary
