"""A short, readable receipt for the terminal, grouped by where each line comes from.

The full versioned record (`pybox exec --json`) stays the source of truth; this is a view.
"""
import os

MECHANISM = {
    "TARGET_EXIT_OBSERVED": "ended by itself",
    "SUPERVISOR_KILL_OBSERVED": "stopped by PyBox at the deadline",
    "IN_CONTAINER_TIMER_CONSISTENT": "ended when the box timer fired (consistent, not proven)",
    "UNKNOWN": "cause not established",
}
CLEANUP = {"REMOVED": "removed and confirmed gone", "ABSENT": "confirmed gone", "NOT_CREATED": "never created",
           "NOT_ATTEMPTED": "never created", "UNCONFIRMED": "NOT CONFIRMED (run: pybox cleanup)"}


def _clean(value):
    """Printable ASCII only: control characters (terminal escapes, newlines) become \\xNN."""
    return "".join(c if " " <= c <= "~" or c in "·→—…−" else "\\x{:02x}".format(ord(c) & 0xFF) for c in str(value))


def _size(n):
    if n is None:
        return "?"
    for unit in ("bytes", "KiB", "MiB"):
        if n < 1024 or unit == "MiB":
            return "{:g} {}".format(round(n, 1), unit) if unit != "bytes" else "{} bytes".format(n)
        n /= 1024


def _mib(n):
    return "{:.1f} MiB".format(n / 1048576)


def _metric(record, name, key="max_observed"):
    item = ((record.get("observed") or {}).get("resources") or {}).get("metrics", {}).get(name)
    return item.get(key) if isinstance(item, dict) else None


def render(record, *, output_dir=None, color=None):
    """Return the receipt as text lines."""
    if color is None:
        color = os.environ.get("NO_COLOR") is None and os.isatty(2)
    bold = (lambda s: "\033[1m" + s + "\033[0m") if color else (lambda s: s)
    dim = (lambda s: "\033[2m" + s + "\033[0m") if color else (lambda s: s)
    c = record.get("configured", {})
    observed = record.get("observed", {})
    state = observed.get("engine_state") or {}
    termination = observed.get("termination") or {}
    capture = record.get("capture", {})
    lifecycle = record.get("lifecycle", {})
    run = ((record.get("identity") or {}).get("labels") or {}).get("io.pybox.run", "")
    lines = []
    head = "PyBox receipt · run {} · image {} · {:.3f} s of {:g} s".format(
        _clean(run[:8]) or "—", _clean(c.get("image_name", "stdlib")), lifecycle.get("attach_elapsed_s") or 0.0, c.get("wall_timeout_s", 2))
    lines.append(bold(head))

    def row(label, value):
        lines.append("  {:<22}{}".format(label, _clean(value)))

    lines.append("")
    lines.append(bold("From the container engine") + dim("  checked before start, read back after"))
    exit_code = state.get("ExitCode") if state.get("Status") == "exited" else None
    row("Exit code", "{} ({})".format(exit_code, MECHANISM.get(termination.get("mechanism"), "cause not established"))
        if exit_code is not None else "not observed")
    verified = observed.get("policy_verified_before_start")
    row("Settings checked", "yes, before the program started" if verified else "NO (the program did not start)")
    row("Mac folders shared", "none" if verified else "—")
    row("Network", "none" if verified else "—")
    row("Limits", "{} MiB · {} processes · {:g} CPU · {:g} s (+1 s box timer)".format(
        c.get("memory_bytes", 0) // 1048576, c.get("pids"), c.get("cpu_cores", 0), c.get("wall_timeout_s", 2)))
    if state.get("OOMKilled"):
        row("Out of memory", "reported by the engine")
    cleanup = record.get("cleanup", {}).get("status")
    row("Box", CLEANUP.get(cleanup, cleanup or "—"))

    lines.append("")
    lines.append(bold("From the Linux kernel") + dim("  sampled while it ran, from outside the box"))
    resources = observed.get("resources") or {}
    if resources.get("status") == "COLLECTED":
        peak = _metric(record, "memory.peak")
        row("Memory peak", "{} of {} MiB".format(_mib(peak), c.get("memory_bytes", 0) // 1048576) if peak is not None else "not read")
        pids = _metric(record, "pids.peak")
        row("Processes peak", "{} of {}".format(pids, c.get("pids")) if pids is not None else "not read")
        throttled = _metric(record, "cpu.stat", "delta")
        if isinstance(throttled, dict):
            row("CPU throttled", "{} periods".format(throttled.get("nr_throttled", 0)))
        oom = _metric(record, "memory.events", "last")
        if isinstance(oom, dict) and oom.get("oom_kill"):
            row("Out-of-memory kills", str(oom["oom_kill"]))
    else:
        row("Counters", "unavailable ({})".format((resources.get("error") or "not collected")[:60]))

    lines.append("")
    lines.append(bold("From the program") + dim("  untrusted: a program can print or write anything"))
    out_bytes = len((capture.get("stdout") or "").encode())
    err_bytes = len((capture.get("stderr") or "").encode())
    row("Printed", "{} on stdout{}, {} on stderr{}".format(
        _size(out_bytes), " (cut)" if capture.get("stdout_truncated") else "",
        _size(err_bytes), " (cut)" if capture.get("stderr_truncated") else ""))
    files = record.get("files")
    if files:
        if files.get("inputs"):
            row("Files in", "{} file(s), {}".format(len(files["inputs"]), _size(sum(f["bytes"] for f in files["inputs"]))))
        outputs = files.get("outputs")
        if outputs is not None:
            where = " → " + output_dir if output_dir and outputs else ""
            row("Files out", "{} file(s), {}{}".format(len(outputs), _size(sum(f["bytes"] for f in outputs)), where))
            if files.get("outputs_skipped"):
                skipped = files["outputs_skipped"]
                row("Not brought back", ", ".join(skipped[:5]) + (" and {} more".format(len(skipped) - 5) if len(skipped) > 5 else ""))
            if files.get("outputs_error"):
                row("Transfer", files["outputs_error"])

    lines.append("")
    lines.append(bold("Not known") + dim("  PyBox says so instead of guessing"))
    row("", "final counters (the box can vanish between readings) · exact clock alignment")
    error = None
    for reason in record.get("explanations", []):
        if reason.get("code") == "RUNNER_ERROR":
            error = reason.get("detail")
    if error:
        lines.append("")
        lines.append(bold("Problem") + "  " + _clean(error[:300]))
    return lines
