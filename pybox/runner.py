import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional, Union


MAX_OUTPUT_BYTES = 1024 * 1024
MAX_TIMEOUT_S = 60.0
TERM_GRACE_S = 0.15
CLEANUP_GRACE_S = 0.6
POLL_INTERVAL_S = 0.05
MAX_CPU_LIMIT_S = 60
CPU_BOOTSTRAP = Path(__file__).with_name("_cpu_bootstrap.py")


class RunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunResult:
    pid: int
    returncode: Optional[int]
    elapsed_s: float
    stdout: str
    stderr: str
    timed_out: bool
    stdout_truncated: bool
    stderr_truncated: bool
    output_complete: bool
    group_cleanup_confirmed: bool
    runner_error: Optional[str]
    cpu_soft_limit_s: Optional[int] = None
    cpu_hard_limit_s: Optional[int] = None
    cpu_limit_installed: bool = False
    termination_signal: Optional[str] = None


def run_file(
    path: Union[str, os.PathLike],
    *,
    unsafe_local: bool = False,
    timeout_s: float = 2.0,
    max_output_bytes: int = 65536,
    cpu_soft_limit_s: Optional[int] = None,
) -> RunResult:
    if unsafe_local is not True:
        raise PermissionError(
            "UNSAFE LOCAL execution requires unsafe_local=True; this is not a sandbox"
        )
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
        raise ValueError("timeout_s must be a finite number greater than 0 and at most 60")
    try:
        timeout_s = float(timeout_s)
    except OverflowError as exc:
        raise ValueError("timeout_s is too large") from exc
    if not math.isfinite(timeout_s) or not 0 < timeout_s <= MAX_TIMEOUT_S:
        raise ValueError("timeout_s must be a finite number greater than 0 and at most 60")
    if (
        cpu_soft_limit_s is not None
        and (
            isinstance(cpu_soft_limit_s, bool)
            or not isinstance(cpu_soft_limit_s, int)
            or not 1 <= cpu_soft_limit_s <= MAX_CPU_LIMIT_S
        )
    ):
        raise ValueError("cpu_soft_limit_s must be an integer from 1 to 60 CPU seconds, or None")
    if (
        isinstance(max_output_bytes, bool)
        or not isinstance(max_output_bytes, int)
        or not 1 <= max_output_bytes <= MAX_OUTPUT_BYTES
    ):
        raise ValueError("max_output_bytes must be an integer from 1 to 1048576 per stream")
    try:
        source = Path(path).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValueError("path must name an existing readable file") from exc
    if not source.is_file() or not os.access(source, os.R_OK):
        raise ValueError("path must name an existing readable file")
    if os.name != "posix":
        raise RunnerError("this learning runner requires POSIX sessions and signals")
    if cpu_soft_limit_s is not None:
        try:
            import resource

            resource.getrlimit(resource.RLIMIT_CPU)
        except (ImportError, AttributeError, OSError, ValueError) as exc:
            raise RunnerError("per-process RLIMIT_CPU is unavailable") from exc

    captured = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = {"stdout": False, "stderr": False}
    eof = set()
    errors = []
    timed_out = False
    capture_enabled = True
    group_gone = False
    group_probe_failed = False
    # macOS answers EPERM (not ESRCH) while a group holds only unreaped zombies, for
    # example a child of the program waiting for launchd. Keep checking; report it only
    # if the group is still there at the cleanup deadline.
    group_eperm = None
    interruption = None
    process = None
    selector = None
    started = None
    cleanup_started = None
    cleanup_finished = False
    term_sent = False
    kill_sent = False
    close_index = 0
    cpu_reader = None
    cpu_writer = None
    cpu_fds = (None, None)
    cpu_status = bytearray()

    def drain_once(wait_s):
        if not capture_enabled or not selector.get_map():
            time.sleep(wait_s)
            return
        for key, _ in selector.select(wait_s):
            try:
                data = os.read(key.fd, 8192)
            except (BlockingIOError, InterruptedError):
                continue
            if not data:
                eof.add(key.data)
                selector.unregister(key.fileobj)
                key.fileobj.close()
                continue
            if key.data == "cpu_setup":
                cpu_status.extend(data[:max(0, 3 - len(cpu_status))])
                continue
            retained = captured[key.data]
            remaining = max_output_bytes - len(retained)
            retained.extend(data[:remaining])
            if len(data) > remaining:
                truncated[key.data] = True

    def signal_group(sig):
        nonlocal group_eperm
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            group_eperm = exc
        except OSError as exc:
            errors.append("process-group {} failed: {}".format(sig.name, exc))

    try:
        try:
            selector = selectors.DefaultSelector()
        except OSError as exc:
            raise RunnerError("could not create the output selector: {}".format(exc)) from exc
        started = time.monotonic()
        try:
            command = [sys.executable, "-I", "-B", "-u", str(source)]
            pass_fds = ()
            if cpu_soft_limit_s is not None:
                cpu_fds = os.pipe()
                read_fd, write_fd = cpu_fds
                cpu_reader = os.fdopen(read_fd, "rb", buffering=0)
                cpu_writer = os.fdopen(write_fd, "wb", buffering=0)
                pass_fds = (write_fd,)
                command = [
                    sys.executable, "-I", "-B", "-u", str(CPU_BOOTSTRAP),
                    str(write_fd), str(cpu_soft_limit_s), str(source),
                ]
            process = subprocess.Popen(
                command,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                close_fds=True,
                cwd=str(source.parent),
                env={"PATH": os.defpath, "LANG": "C", "LC_ALL": "C"},
                start_new_session=True,
                pass_fds=pass_fds,
            )
        except (OSError, ValueError) as exc:
            raise RunnerError("could not launch Python: {}".format(exc)) from exc
        if cpu_writer is not None:
            cpu_writer.close()
            os.set_blocking(cpu_reader.fileno(), False)
            selector.register(cpu_reader, selectors.EVENT_READ, "cpu_setup")
        for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        deadline = started + timeout_s
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            drain_once(min(POLL_INTERVAL_S, remaining))
    except KeyboardInterrupt as exc:
        interruption = exc
    except Exception as exc:
        if process is None:
            raise
        errors.append("output collection failed: {}".format(exc))
        capture_enabled = False
    finally:
        while True:
            try:
                if process is not None and not cleanup_finished:
                    if cleanup_started is None:
                        cleanup_started = time.monotonic()
                    kill_at = cleanup_started + TERM_GRACE_S
                    cleanup_deadline = cleanup_started + CLEANUP_GRACE_S
                    if not term_sent:
                        signal_group(signal.SIGTERM)
                        term_sent = True
                    process.poll()
                    if not group_gone:
                        try:
                            os.killpg(process.pid, 0)
                        except ProcessLookupError:
                            group_gone = True
                        except PermissionError as exc:
                            group_eperm = exc
                        except OSError as exc:
                            if not group_probe_failed:
                                errors.append("process-group check failed: {}".format(exc))
                                group_probe_failed = True
                    if (
                        process.returncode is not None
                        and group_gone
                        and (not capture_enabled or not selector.get_map())
                    ):
                        cleanup_finished = True
                    else:
                        now = time.monotonic()
                        if now >= cleanup_deadline:
                            process.poll()
                            if not group_gone and group_eperm is not None and not group_probe_failed:
                                errors.append("process-group check failed: {}".format(group_eperm))
                                group_probe_failed = True
                            cleanup_finished = True
                        else:
                            if not kill_sent and now >= kill_at:
                                if not group_gone:
                                    signal_group(signal.SIGKILL)
                                kill_sent = True
                            next_deadline = cleanup_deadline if kill_sent else kill_at
                            wait_s = max(0.0, min(POLL_INTERVAL_S, next_deadline - now))
                            try:
                                drain_once(wait_s)
                            except Exception as exc:
                                errors.append("output collection during cleanup failed: {}".format(exc))
                                capture_enabled = False
                            continue
                resources = (
                    process.stdout if process is not None else None,
                    process.stderr if process is not None else None,
                    cpu_reader if cpu_reader is not None else cpu_fds[0],
                    cpu_writer if cpu_writer is not None else cpu_fds[1],
                    selector,
                )
                while close_index < len(resources):
                    resource = resources[close_index]
                    if isinstance(resource, int):
                        os.close(resource)
                    elif resource is not None:
                        resource.close()
                    close_index += 1
                break
            except KeyboardInterrupt as exc:
                if interruption is not None:
                    raise
                interruption = exc

    if interruption is not None:
        raise interruption

    output_complete = {"stdout", "stderr"}.issubset(eof)
    cpu_limit_installed = cpu_status in (b"R", b"RE") and "cpu_setup" in eof
    if cpu_soft_limit_s is not None and (cpu_status != b"R" or "cpu_setup" not in eof):
        errors.append("CPU-limit bootstrap failed or was not confirmed; target launch not confirmed")
    group_cleanup_confirmed = process.returncode is not None and group_gone
    if process.returncode is None:
        errors.append("direct child could not be reaped within cleanup grace")
    if not group_gone:
        errors.append("process-group disappearance could not be confirmed within cleanup grace")
    if not output_complete:
        errors.append("output collection did not reach EOF on both pipes within cleanup grace")
    termination_signal = None
    if process.returncode is not None and process.returncode < 0:
        try:
            termination_signal = signal.Signals(-process.returncode).name
        except ValueError:
            termination_signal = "signal {}".format(-process.returncode)
    return RunResult(
        pid=process.pid,
        returncode=process.returncode,
        elapsed_s=time.monotonic() - started,
        stdout=captured["stdout"].decode("utf-8", errors="replace"),
        stderr=captured["stderr"].decode("utf-8", errors="replace"),
        timed_out=timed_out,
        stdout_truncated=truncated["stdout"],
        stderr_truncated=truncated["stderr"],
        output_complete=output_complete,
        group_cleanup_confirmed=group_cleanup_confirmed,
        runner_error="; ".join(errors) if errors else None,
        cpu_soft_limit_s=cpu_soft_limit_s,
        cpu_hard_limit_s=cpu_soft_limit_s + 1 if cpu_soft_limit_s is not None else None,
        cpu_limit_installed=cpu_limit_installed,
        termination_signal=termination_signal,
    )
