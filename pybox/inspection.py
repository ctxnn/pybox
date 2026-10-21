"""Versioned inspection records: policy, observations and unknowns stay distinct."""
import copy


def make_record(result, *, image, source_sha256, timeout_s, cap, policy_verified, phase, box=None, collect_outputs=False, linger_s=0.0):
    state=(result.inspection or {}).get('State',{})
    resources=copy.deepcopy(result.resources)
    metrics=resources.get('metrics',{})
    reconciliation=copy.deepcopy(result.reconciliation)
    if reconciliation is not None:
        # Detailed command captures remain in the backwards-compatible raw result.
        operations=reconciliation.pop('operations',[])
        reconciliation['operation_count']=len(operations)
    raw=result.inspection or {}
    host=raw.get('HostConfig',{})
    config=raw.get('Config',{})
    effective=dict(user=config.get('User'),entrypoint=config.get('Entrypoint'),command=config.get('Cmd'),
                   image=config.get('Image'),network=host.get('NetworkMode'),readonly_root=host.get('ReadonlyRootfs'),
                   memory_bytes=host.get('Memory'),memory_plus_swap_bytes=host.get('MemorySwap'),pids=host.get('PidsLimit'),
                   nano_cpus=host.get('NanoCpus'),security_options=host.get('SecurityOpt'),cap_drop=host.get('CapDrop'),
                   cap_add=host.get('CapAdd'),tmpfs=host.get('Tmpfs'),nofile=host.get('Ulimits'),engine_log=host.get('LogConfig'))
    memory=box.memory if box else 134217728
    files=None
    if box is not None and box.files and (result.inputs or collect_outputs):
        files=dict(inputs=copy.deepcopy(result.inputs),inputs_provenance='copies of caller files sent on standard input; the program can change its copies',
                   outputs=copy.deepcopy(result.outputs) if collect_outputs else None,outputs_skipped=list(result.outputs_skipped),
                   outputs_error=result.outputs_error,
                   outputs_provenance='made by the untrusted program and appended to its standard output; parsed and bounded by the supervisor; untrusted content')
    reasons=[]
    if result.cancelled: reasons.append(dict(code='CANCELLED',evidence=['supervisor cancellation']))
    if result.timeouts: reasons.append(dict(code='DEADLINE_REACHED',limits=list(result.timeouts),evidence=['supervisor clocks']))
    if result.runner_error: reasons.append(dict(code='RUNNER_ERROR',detail=result.runner_error,evidence=['supervisor/control plane']))
    if result.returncode is not None:
        reasons.append(dict(code='TARGET_EXIT_OBSERVED',value=result.returncode,evidence=['Docker terminal State']))
    if result.termination_evidence.get('pybox_kill_attempted'):
        reasons.append(dict(code='SUPERVISOR_KILL_ATTEMPTED',acknowledged=result.termination_evidence.get('pybox_kill_sent'),
                            evidence=['recorded engine command attempt; see termination evidence']))
    if state.get('OOMKilled') is True:
        reasons.append(dict(code='OOM_REPORTED_BY_ENGINE',evidence=['Docker State.OOMKilled'],
                            limitation='does not establish which process died or make exit 137 uniquely OOM'))
    oom=metrics.get('memory.events')
    if oom and oom['last'].get('oom_kill',0)>0:
        reasons.append(dict(code='OOM_KILL_COUNTER_OBSERVED',count=oom['last']['oom_kill'],
                            evidence=['trusted guest memory.events; live sample']))
    pids=metrics.get('pids.events')
    if pids and pids['last'].get('max',0)>0:
        reasons.append(dict(code='TASK_LIMIT_EVENT_OBSERVED',count=pids['last']['max'],
                            evidence=['trusted guest pids.events; live sample']))
    cpu=metrics.get('cpu.stat')
    if cpu and cpu['last'].get('nr_throttled',0)>0:
        reasons.append(dict(code='CPU_THROTTLING_OBSERVED',periods=cpu['last']['nr_throttled'],
                            evidence=['trusted guest cpu.stat; live sample'],limitation='throttling does not imply termination'))
    if resources.get('status')!='COLLECTED':
        reasons.append(dict(code='COUNTERS_UNAVAILABLE',detail=resources.get('error'),evidence=['collector status']))
    if not policy_verified:
        reasons.append(dict(code='POLICY_NOT_VERIFIED_BEFORE_START',evidence=['supervisor lifecycle']))
    return dict(schema_version=1,backend='container',identity=copy.deepcopy(result.identity),container_id=result.container_id,
                submission=dict(source_sha256=source_sha256),
                configured=dict(image=image,image_name=box.image if box else 'stdlib',
                    image_recipe_sha256=box.recipe if box else None,wall_timeout_s=float(timeout_s),
                    bootstrap=bool(box and box.files),final_reading_linger_s=linger_s,
                    image_note=None if not box or box.image in ('stdlib','data') else
                        'your own image: its packages can run code at interpreter start-up, before the fixed helper',
                    watcher_transport=next((o.get('transport') for o in result.operations if o.get('phase')=='observe'),None),
                    guest_timer_s=result.timer_limit_s,memory_bytes=memory,
                    memory_plus_swap_bytes=memory,pids=box.pids if box else 32,cpu_cores=box.nano_cpus/1e9 if box else 0.5,
                    output_bytes_per_stream=cap,
                    network='none',user='10000:10000',readonly_root=True,tmpfs_bytes=box.tmpfs_bytes if box else 16777216,
                    no_new_privileges=True,cap_drop=['ALL'],seccomp='runtime default',nofile=128,engine_log='none'),
                observed=dict(policy_verified_before_start=policy_verified,effective_policy=effective,
                    policy_provenance='identity-verified Docker inspect readback; policy verification stated separately',engine_state=copy.deepcopy(state),
                    resources=resources,termination=copy.deepcopy(result.termination_evidence)),
                capture=dict(stdout=result.stdout,stderr=result.stderr,output_complete=result.output_complete,
                    input_complete=next((o.get('input_complete') for o in result.operations if o['phase']=='start'),None),
                    stdout_truncated=result.stdout_truncated,stderr_truncated=result.stderr_truncated,
                    provenance='target byte streams via bounded Docker attach; untrusted content'),
                lifecycle=dict(last_phase=phase,cancelled=result.cancelled,timeouts=list(result.timeouts),
                    wall_start_monotonic=result.wall_start_monotonic,wall_deadline_monotonic=result.wall_deadline_monotonic,
                    attach_elapsed_s=result.elapsed_s,lifecycle_elapsed_s=result.lifecycle_elapsed_s),
                cleanup=dict(status=result.cleanup_status,removed=result.removed,reconciliation=reconciliation),
                clock_domains=dict(supervisor='Mac UTC and Mac monotonic',engine='guest Docker daemon UTC',
                    counters='guest uptime; samples are non-atomic',utc_alignment='unmeasured'),
                final_reading=None if not linger_s else dict(linger_s=linger_s,
                    note='the in-box helper keeps the box open this long after the program so the watcher can read cumulative peaks; '
                         'it runs as the program\'s user, so a program can cut it short'),
                unknown=dict(final_resource_counters=True,exact_termination_cause=True,
                    absolute_clock_alignment=True,
                    limitation='live samples can miss startup/teardown; deltas cover successful reads, not lifetime; exit code alone is not a cause'),
                files=files,explanations=reasons)
