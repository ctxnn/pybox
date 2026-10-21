#!/bin/sh
# Read-only, finite guest collector, launched before container START.
# A separate guest timeout bounds this collector even if the Mac disappears.
set -eu
cid=$1
# Optional spacing after the first second, for longer runs (default 0.05 s, at most 9.99 s).
interval=${2:-0.05}
case "$cid" in ''|*[!0-9a-f]*) exit 90;; esac
case "$interval" in [0-9].[0-9][0-9]) ;; *) exit 92;; esac
[ "${#cid}" -eq 64 ]
[ "$(stat -f -c %T /sys/fs/cgroup)" = cgroup2fs ]
printf 'ARMED\t%s\n' "$cid"
cg=''
for attempt in $(seq 1 100); do
    for candidate in "/sys/fs/cgroup/docker/$cid" "/sys/fs/cgroup/system.slice/docker-$cid.scope"; do
        if [ -d "$candidate" ]; then cg=$candidate; break; fi
    done
    [ -z "$cg" ] || break
    sleep 0.02
done
if [ -z "$cg" ]; then printf 'STOP\tnot_seen\n'; exit 0; fi
[ "$(readlink -f "$cg")" = "$cg" ]
inode=$(stat -c %i "$cg")
owncg=$(sed -n 's/^0:://p' /proc/self/cgroup)
[ "/sys/fs/cgroup$owncg" != "$cg" ]
printf 'BIND\t%s\t%s\t%s\n' "$cg" "$inode" "$owncg"
files='cgroup.events memory.max memory.swap.max memory.swap.current memory.current memory.peak memory.events memory.events.local pids.max pids.current pids.peak pids.events cpu.max cpu.max.burst cpu.stat'
seen_live=0
for sample in $(seq 0 63); do
    if [ ! -d "$cg" ]; then printf 'STOP\tdisappeared\n'; exit 0; fi
    current_inode=$(stat -c %i "$cg" 2>/dev/null) || { printf 'STOP\tdisappeared\n'; exit 0; }
    [ "$current_inode" = "$inode" ] || exit 91
    printf 'SAMPLE\t%s\t%s\n' "$sample" "$(cut -d' ' -f1 /proc/uptime)"
    for f in $files; do
        if value=$(cat "$cg/$f" 2>/dev/null); then
            printf 'VALUE\t%s\t%s\n' "$f" "$(printf '%s' "$value" | tr '\n' ';')"
        else
            printf 'UNAVAILABLE\t%s\n' "$f"
        fi
    done
    printf 'END\n'
    if [ ! -d "$cg" ]; then printf 'STOP\tdisappeared\n'; exit 0; fi
    if grep -q '^populated 1$' "$cg/cgroup.events" 2>/dev/null; then seen_live=1; fi
    if [ "$seen_live" -eq 1 ] && grep -q '^populated 0$' "$cg/cgroup.events" 2>/dev/null; then printf 'STOP\tunpopulated\n'; exit 0; fi
    # The first 20 samples are always 0.05 s apart, so short programs are seen in detail.
    if [ "$sample" -lt 20 ]; then sleep 0.05; else sleep "$interval"; fi
done
printf 'STOP\tsample_cap\n'
