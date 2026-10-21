#!/bin/sh
# Finite trusted VM observer. Never runs inside the measured container/cgroup.
# Only the readiness file is written; resource controller files are read-only.
set -eu
pid=$1
cid=$2
case "$pid" in ''|*[!0-9]*) exit 91;; esac
case "$cid" in ''|*[!0-9a-f]*) exit 92;; esac
[ "${#cid}" -eq 64 ]
cgrel=$(sed -n 's/^0:://p' "/proc/$pid/cgroup")
case "$cgrel" in "/docker/$cid"|"/system.slice/docker-$cid.scope") ;; *) exit 93;; esac
cg="/sys/fs/cgroup$cgrel"
[ "$(readlink -f "$cg")" = "$cg" ]
inode=$(stat -c %i "$cg")
cmd=$(tr '\000' '|' < "/proc/$pid/cmdline")
case "$cmd" in 'timeout|-s|KILL|'*'|python|-I|-B|-u|-|') ;; *) exit 94;; esac
[ "$(awk '/^NSpid:/ {print $NF}' "/proc/$pid/status")" = 1 ]
owncg=$(sed -n 's/^0:://p' /proc/self/cgroup)
[ "$owncg" != "$cgrel" ]
printf 'META\tcgroup\t%s\nMETA\tinode\t%s\nMETA\tpid\t%s\n' "$cgrel" "$inode" "$pid"
printf 'META\tcmdline\t%s\nMETA\tobserver_cgroup\t%s\n' "$cmd" "$owncg"
printf 'META\tkernel\t%s\n' "$(uname -srvm)"
printf 'META\tpid_stat\t%s\n' "$(cat "/proc/$pid/stat")"
printf 'META\tswaps\t%s\n' "$(tr '\t\n' ' ;' < /proc/swaps)"
children=$(cat "/proc/$pid/task/$pid/children")
set -- $children
[ "$#" -eq 1 ]
child=$1
[ "$(sed -n 's/^0:://p' "/proc/$child/cgroup")" = "$cgrel" ]
printf 'META\tchild_cmdline\t%s\n' "$(tr '\000' '|' < "/proc/$child/cmdline")"
printf 'META\tchild_limits\t%s\n' "$(tr '\t\n' ' ;' < "/proc/$child/limits")"
files='cgroup.events memory.max memory.swap.max memory.swap.current memory.oom.group memory.current memory.peak memory.events memory.events.local pids.max pids.current pids.peak pids.events cpu.max cpu.max.burst cpu.stat'
sample=0
start=$(cut -d. -f1 /proc/uptime)
while [ "$sample" -lt 64 ]; do
    if [ ! -d "$cg" ]; then printf 'STOP\tdisappeared\n'; exit 0; fi
    [ "$(stat -c %i "$cg")" = "$inode" ] || exit 95
    printf 'SAMPLE\t%s\t%s\n' "$sample" "$(cut -d' ' -f1 /proc/uptime)"
    for f in $files; do
        if value=$(cat "$cg/$f" 2>/dev/null); then
            printf 'VALUE\t%s\t%s\n' "$f" "$(printf '%s' "$value" | tr '\n' ';')"
        else
            printf 'UNAVAILABLE\t%s\n' "$f"
        fi
    done
    printf 'END\n'
    if [ "$sample" -eq 0 ]; then
        # Controlled fixtures wait for this file; no host share or docker exec.
        [ "$(sed -n 's/^0:://p' "/proc/$pid/cgroup")" = "$cgrel" ]
        : > "/proc/$pid/root/tmp/pybox-m3c-observer-ready"
        printf 'READY\n'
    fi
    if [ ! -d "$cg" ]; then printf 'STOP\tdisappeared\n'; exit 0; fi
    if grep -q '^populated 0$' "$cg/cgroup.events" 2>/dev/null; then printf 'STOP\tunpopulated\n'; exit 0; fi
    now=$(cut -d. -f1 /proc/uptime)
    if [ "$((now-start))" -ge 10 ]; then printf 'STOP\tbudget\n'; exit 0; fi
    sample=$((sample+1))
    sleep 0.1
done
printf 'STOP\tsample_cap\n'
