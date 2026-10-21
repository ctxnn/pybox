import copy
import datetime
import fcntl
import hashlib
from itertools import islice
import json
import math
import os
from pathlib import Path
import platform
import pwd
import re
import selectors
import shlex
import signal
import stat
import subprocess
import sys
import time
import uuid
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Optional

from . import boxes, observation
from .inspection import make_record


IMAGE = "python@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f"
PROFILE = "pybox"
CONTEXT_NAME = "colima-pybox"
# Only these directories are searched for docker/colima; never $PATH.
TOOL_DIRS = (Path("/opt/homebrew/bin"), Path("/usr/local/bin"))


def _find_tool(name):
    """First allowlisted candidate that exists; the guard verifies it before use."""
    for directory in TOOL_DIRS:
        if (directory / name).exists():
            return directory / name
    return TOOL_DIRS[0] / name


# The runtime belongs to whoever runs PyBox. For the originally qualified
# installation these resolve to the same paths that were hard-coded before M8.
HOME = Path.home()
USER = pwd.getpwuid(os.getuid()).pw_name
ROOT = HOME / ".pybox/runtime"
OWNER_FILE = ROOT / "installation.json"
COLIMA = ROOT / "colima"
LIMA = COLIMA / "_lima"
DOCKER_CONFIG = ROOT / "docker"
SOCKET = COLIMA / PROFILE / "docker.sock"
# Docker stores each context's metadata under sha256(context name).
CONTEXT = DOCKER_CONFIG / "contexts/meta" / hashlib.sha256(CONTEXT_NAME.encode()).hexdigest() / "meta.json"
DOCKER_BIN = _find_tool("docker")
COLIMA_BIN = _find_tool("colima")
PREFIX = [str(DOCKER_BIN), "--config", str(DOCKER_CONFIG), "--context", CONTEXT_NAME]
ENV = dict(HOME=str(HOME), USER=USER, LOGNAME=USER,
           PATH=str(DOCKER_BIN.parent) + ":/usr/bin:/bin:/usr/sbin:/sbin", LANG="C", LC_ALL="C",
           COLIMA_HOME=str(COLIMA), LIMA_HOME=str(LIMA), DOCKER_CONFIG=str(DOCKER_CONFIG),
           COLIMA_CACHE_HOME=str(ROOT / "cache/colima"), TMPDIR=str(ROOT / "tmp"))
MAX_SOURCE_BYTES = 65536
OPERATION_TIMEOUTS = dict(create=5.0, start=2.0, inspect=2.0, query=2.0, kill=2.0, remove=3.0)
CLEANUP_BUDGET_S = 15.0
EXPIRY_S = 120
RESOLVE_MARGIN_S = 60
TIMER_MARGIN_S = 1.0
MAX_RECONCILE_CONTAINERS = 128
TMPFS = boxes.TMPFS
IMAGES_FILE = ROOT / "images.json"
RECIPES = ROOT / "recipes"
POLICY = ('portForwards:\n  - guestIP: "0.0.0.0"\n    guestIPMustBeZero: false\n'
          '    guestPortRange: [1, 65535]\n    hostPortRange: [1, 65535]\n'
          '    proto: any\n    ignore: true\n')
INSPECT = ('{"Id":{{json .Id}},"Name":{{json .Name}},"State":{{json .State}},"Image":{{json .Image}},'
           '"Config":{"Image":{{json .Config.Image}},"User":{{json .Config.User}},'
           '"Cmd":{{json .Config.Cmd}},"Entrypoint":{{json .Config.Entrypoint}},'
           '"Labels":{{json .Config.Labels}},"Tty":{{json .Config.Tty}},"OpenStdin":{{json .Config.OpenStdin}}},'
           '"HostConfig":{{json .HostConfig}},"Mounts":{{json .Mounts}},"NetworkSettings":{{json .NetworkSettings}}}')


@dataclass(frozen=True)
class ContainerResult:
    backend: str
    stdout: str
    stderr: str
    returncode: Optional[int]
    elapsed_s: float
    timed_out: bool
    stdout_truncated: bool
    stderr_truncated: bool
    output_complete: bool
    runner_error: Optional[str]
    container_id: Optional[str]
    removed: bool
    inspection: Optional[dict]
    operations: list
    identity: Optional[dict] = None
    cleanup_status: str = "UNCONFIRMED"
    timeouts: list = field(default_factory=list)
    wall_start_monotonic: Optional[float] = None
    wall_deadline_monotonic: Optional[float] = None
    lifecycle_elapsed_s: float = 0.0
    timer_limit_s: Optional[float] = None
    termination_evidence: dict = field(default_factory=dict)
    reconciliation: Optional[dict] = None
    resources: dict = field(default_factory=dict)
    record: dict = field(default_factory=dict)
    cancelled: bool = False
    image: str = "stdlib"
    inputs: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    outputs_skipped: list = field(default_factory=list)
    outputs_error: Optional[str] = None
    # (name, bytes) pairs made by the untrusted program; written to the Mac only by the caller.
    output_files: tuple = ()


@dataclass(frozen=True)
class CleanupResult:
    owner: Optional[str] = None
    found: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    pending_attempts: list = field(default_factory=list)
    operations: list = field(default_factory=list)
    complete: bool = False
    admission_allowed: bool = False
    runner_error: Optional[str] = None


def _check_platform():
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise RuntimeError("restricted engine supports macOS on Apple Silicon (arm64) only")


def _check_tool(path):
    """An allowlisted CLI whose resolved file only its owner or root can modify."""
    if path.parent not in TOOL_DIRS:
        raise RuntimeError("tool outside the allowlisted directories: {}".format(path))
    try:
        real = path.resolve(strict=True)
        s = real.stat()
    except OSError as exc:
        raise RuntimeError("required tool missing: {} (install with: brew install colima docker)".format(path)) from exc
    if not stat.S_ISREG(s.st_mode) or not s.st_mode & 0o111 or s.st_mode & 0o022 or s.st_uid not in (0, os.getuid()):
        raise RuntimeError("tool is not a private executable: {}".format(real))
    return real


def _guard():
    uid = os.getuid()
    _check_platform()
    if HOME != Path.home() or HOME.resolve() != HOME or HOME.stat().st_uid != uid:
        raise RuntimeError("dedicated runtime home anchor mismatch")
    for tool in (DOCKER_BIN, COLIMA_BIN):
        _check_tool(tool)
    if not os.path.lexists(ROOT) or not os.path.lexists(COLIMA / PROFILE):
        raise RuntimeError("restricted runtime is not set up (run: pybox setup)")
    if not os.path.lexists(CONTEXT) or not os.path.lexists(SOCKET):
        raise RuntimeError("dedicated VM is not running (start it with: pybox vm start; check: pybox doctor)")
    paths = [ROOT.parent, ROOT, COLIMA, LIMA, LIMA / "_config", COLIMA / "pybox", DOCKER_CONFIG,
             ROOT / "cache", ROOT / "cache/colima", ROOT / "cache/colima/caches", ROOT / "tmp", ROOT / "logs"]
    for p in paths:
        s = p.lstat()
        if not stat.S_ISDIR(s.st_mode) or p.resolve() != p or p.is_symlink() or s.st_uid != uid or s.st_mode & 0o077:
            raise RuntimeError("missing/nonprivate/noncanonical dedicated directory: {}".format(p))
    for p in [LIMA / "_config/override.yaml", DOCKER_CONFIG / "config.json", CONTEXT]:
        s = p.lstat()
        if not stat.S_ISREG(s.st_mode) or p.resolve() != p or p.is_symlink() or s.st_uid != uid or s.st_mode & 0o022:
            raise RuntimeError("unsafe dedicated configuration path: {}".format(p))
    if (LIMA / "_config/override.yaml").read_text() != POLICY:
        raise RuntimeError("dedicated forwarding override changed")
    if json.loads((DOCKER_CONFIG / "config.json").read_text()) != {
        "auths": {"https://index.docker.io/v1/": {}}, "credsStore": "", "credHelpers": {},
    }:
        raise RuntimeError("dedicated anonymous Docker configuration changed")
    context = json.loads(CONTEXT.read_text())
    endpoint = context.get("Endpoints", {}).get("docker", {})
    if context.get("Name") != "colima-pybox" or set(context.get("Endpoints", {})) != {"docker"} or endpoint != {
        "Host": "unix://" + str(SOCKET), "SkipTLSVerify": False,
    }:
        raise RuntimeError("dedicated Docker context does not name the approved local Unix socket")
    s = SOCKET.lstat()
    if not stat.S_ISSOCK(s.st_mode) or SOCKET.resolve() != SOCKET or SOCKET.is_symlink() or s.st_uid != uid:
        raise RuntimeError("dedicated Docker Unix socket path/type/ownership mismatch")


def _installation_owner():
    _guard()
    try:
        fd = os.open(OWNER_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w") as file:
            json.dump(dict(version=1, owner=uuid.uuid4().hex), file)
            file.flush()
            os.fsync(file.fileno())
    fd = os.open(OWNER_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "r") as file:
        s = os.fstat(file.fileno())
        if (not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077
            or s.st_nlink != 1 or s.st_size > 4096 or OWNER_FILE.resolve() != OWNER_FILE):
            raise RuntimeError("unsafe installation identity file")
        data = json.load(file)
    if (not isinstance(data, dict) or set(data) != {"version", "owner"} or type(data["version"]) is not int
        or data["version"] != 1 or not isinstance(data["owner"], str) or not re.fullmatch(r"[0-9a-f]{32}", data["owner"])):
        raise RuntimeError("invalid installation identity; will not replace existing metadata")
    return data["owner"]


def local_images():
    """Images built by `pybox setup --with …`, recorded in a private file; {} if none."""
    if not os.path.lexists(IMAGES_FILE):
        return {}
    fd = os.open(IMAGES_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "r") as file:
        _private_file(file.fileno())
        if os.fstat(file.fileno()).st_size > 65536:
            raise RuntimeError("oversize image record")
        data = json.load(file)
    images = data.get("images") if isinstance(data, dict) and data.get("version") == 1 else None
    if not isinstance(images, dict) or any(
            not isinstance(name, str) or not boxes.IMAGE_NAME.fullmatch(name) or not isinstance(entry, dict)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(entry.get("id"))) or entry.get("base") != IMAGE
            or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("recipe_sha256")))
            for name, entry in images.items()):
        raise RuntimeError("invalid local image record")
    return images


def read_recipe(name):
    """The private copy of a custom image's lock file, saved when it was built."""
    path = RECIPES / (boxes.check_image_name(name) + ".lock")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "r") as file:
        _private_file(file.fileno())
        if os.fstat(file.fileno()).st_size > boxes.MAX_LOCK_BYTES:
            raise RuntimeError("oversize recipe")
        return file.read()


def expected_recipe(name):
    """The recipe fingerprint an image must have been built from."""
    if name == "data":
        return boxes.recipe_sha256(IMAGE)
    try:
        return boxes.recipe_sha256(IMAGE, boxes.check_lock(read_recipe(name)))
    except (OSError, ValueError) as exc:
        raise RuntimeError("recipe for image '{}' is missing or invalid: {}".format(name, exc)) from exc


def _rebuild_hint(name):
    return "pybox setup --yes --with data" if name == "data" else "pybox image build {} --lock FILE".format(name)


def resolve_box(image="stdlib", files=False, moves_files=None):
    """The box for a run. stdlib is the pinned registry digest; others are locally built IDs."""
    if image == "stdlib":
        return boxes.make_box("stdlib", IMAGE, files, moves_files=moves_files)
    boxes.check_image_name(image)
    entry = local_images().get(image)
    if entry is None:
        raise RuntimeError("image '{}' is not installed (run: {})".format(image, _rebuild_hint(image)))
    if entry["recipe_sha256"] != expected_recipe(image):
        raise RuntimeError("image '{}' was built from a different recipe (rebuild: {})".format(image, _rebuild_hint(image)))
    return boxes.make_box(image, entry["id"], files, recipe=entry["recipe_sha256"], moves_files=moves_files)


STDLIB_BOX = boxes.make_box("stdlib", IMAGE)


def _timer_args(timeout_s, box=None):
    program = ["-c", boxes.BOOTSTRAP] if box is not None and box.files else ["-"]
    return ["-s", "KILL", format(float(timeout_s) + TIMER_MARGIN_S, ".17g"), "python", "-I", "-B", "-u", *program]


def _create_args(identity, timeout_s=2.0, box=None):
    box = box or STDLIB_BOX
    labels = [item for key, value in identity["labels"].items() for item in ["--label", key + "=" + value]]
    memory = "{}m".format(box.memory // boxes.MIB)
    return ["container", "create", "--name", identity["name"], "--label", "io.pybox.checkpoint=m3a-step4",
            *labels, "--pull=never", "--platform=linux/arm64", "--interactive",
            "--network=none", "--user=10000:10000", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--read-only", "--tmpfs", "/tmp:" + box.tmpfs, "--memory=" + memory, "--memory-swap=" + memory,
            "--pids-limit={}".format(box.pids), "--cpus=" + box.cpus, "--ulimit", "nofile=128:128", "--log-driver=none",
            "--privileged=false", "--restart=no", "--ipc=private", "--entrypoint=timeout", box.ref, *_timer_args(timeout_s, box)]


def _capture(argv, input_data=None, timeout_s=10.0, cap=65536, *, deadline=None, on_stdout=None, cancel=None):
    started = time.monotonic()
    deadline = min(started + timeout_s, deadline) if deadline is not None else started + timeout_s
    start_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    captured = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = {"stdout": False, "stderr": False}
    eof = set()
    sent = 0
    timed_out = False
    cancelled = False
    process = None
    with selectors.DefaultSelector() as selector:
        try:
            process = subprocess.Popen(argv, stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(ENV), shell=False,
                                       bufsize=0, close_fds=True, start_new_session=True)
            for name, pipe in [("stdout", process.stdout), ("stderr", process.stderr)]:
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, name)
            if input_data:
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
            elif process.stdin is not None:
                process.stdin.close()
            while selector.get_map() or process.poll() is None:
                if cancel is not None and cancel.is_set():
                    cancelled = True
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                if not selector.get_map():
                    time.sleep(min(0.02, remaining))
                    continue
                for key, _ in selector.select(min(0.05, remaining)):
                    if key.data == "stdin":
                        try:
                            sent += os.write(key.fd, input_data[sent:sent + 8192])
                        except BrokenPipeError:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                            continue
                        except (BlockingIOError, InterruptedError):
                            continue
                        if sent == len(input_data):
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                        continue
                    try:
                        data = os.read(key.fd, 8192)
                    except (BlockingIOError, InterruptedError):
                        continue
                    if not data:
                        eof.add(key.data)
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                        continue
                    if key.data == "stdout" and on_stdout is not None:
                        on_stdout(data)
                    room = cap - len(captured[key.data])
                    captured[key.data].extend(data[:room])
                    truncated[key.data] |= len(data) > room
        finally:
            if process is not None:
                try:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                        try:
                            process.wait(timeout=0.25)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=0.75)
                finally:
                    for pipe in [process.stdin, process.stdout, process.stderr]:
                        if pipe is not None:
                            pipe.close()
    return dict(argv=argv, start_utc=start_utc, end_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                returncode=process.returncode, elapsed_s=time.monotonic() - started,
                timed_out=timed_out, stdout=captured["stdout"].decode("utf-8", errors="replace"),
                stderr=captured["stderr"].decode("utf-8", errors="replace"), stdout_truncated=truncated["stdout"],
                stderr_truncated=truncated["stderr"], output_complete=eof == {"stdout", "stderr"},
                input_complete=input_data is None or sent == len(input_data), cancelled=cancelled)


SSH_BIN = Path("/usr/bin/ssh")
SSH_HOST = "lima-colima-" + PROFILE
# Every keyword Lima writes into its ssh.config. Anything else makes PyBox fall back.
_LIMA_SSH_KEYS = frozenset(("identityfile", "stricthostkeychecking", "userknownhostsfile", "nohostauthenticationforlocalhost",
                            "preferredauthentications", "compression", "batchmode", "identitiesonly", "gssapiauthentication",
                            "ciphers", "user", "controlmaster", "controlpath", "controlpersist", "hostname", "port"))


def _private_entry(path, *, directory=False):
    s = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if not kind(s.st_mode) or path.is_symlink() or path.resolve() != path or s.st_uid != os.getuid() or s.st_mode & 0o077:
        raise RuntimeError("not private: {}".format(path))


def _lima_ssh_settings(text):
    """Read Lima's ssh.config with an allowlist: one Host block, known keywords only.

    Only four values are used, and each must be exactly what this installation expects;
    ssh itself never reads the file (it runs with -F /dev/null).
    """
    if len(text) > 16384:
        raise RuntimeError("unexpected Lima ssh config")
    values, host = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition(" ")
        value = value.strip()
        if '"' in key or "=" in key:
            raise RuntimeError("unexpected Lima ssh config keyword")
        if key.lower() == "host":
            if host is not None or value != SSH_HOST:
                raise RuntimeError("unexpected Lima ssh config host")
            host = value
            continue
        if host is None or key.lower() not in _LIMA_SSH_KEYS or key.lower() in values:
            raise RuntimeError("unexpected Lima ssh config keyword")
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            value = value[1:-1]
        values[key.lower()] = value
    instance = LIMA / SSH_HOST.removeprefix("lima-")
    key_file, socket_path = LIMA / "_config/user", instance / "ssh.sock"
    if (values.get("hostname") != "127.0.0.1" or not re.fullmatch(r"[1-9][0-9]{0,4}", values.get("port", ""))
            or int(values["port"]) > 65535 or values.get("user") != USER or values.get("identityfile") != str(key_file)
            or values.get("controlpath") != str(socket_path) or "%" in str(socket_path) or "%" in str(key_file)):
        raise RuntimeError("unexpected Lima ssh config values")
    _private_entry(key_file)
    return dict(port=values["port"], key=str(key_file), socket=str(socket_path))


def _observer_transport(remote):
    """How the watcher reaches the VM.

    `colima ssh` starts two helper programs before connecting (about 0.15 s). PyBox can
    instead run /usr/bin/ssh itself over Lima's already-open connection, taking only the
    user, port, key and connection socket from Lima's config after checking each one, with
    every other ssh setting fixed here (-F /dev/null). If any check fails it falls back to
    `colima ssh`. Both reach the same VM as the same user with the same host-key policy.
    """
    config = LIMA / SSH_HOST.removeprefix("lima-") / "ssh.config"
    try:
        _private_entry(config.parent, directory=True)
        _private_entry(config)
        s = SSH_BIN.stat()
        if not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
            raise RuntimeError("ssh is not a root-owned system binary")
        lima = _lima_ssh_settings(config.read_text())
        options = ["BatchMode=yes", "IdentitiesOnly=yes", "IdentityFile=" + lima["key"], "User=" + USER,
                   "Port=" + lima["port"], "ControlMaster=no", "ControlPath=" + lima["socket"],
                   "StrictHostKeyChecking=no", "UserKnownHostsFile=/dev/null", "PreferredAuthentications=publickey",
                   "LogLevel=ERROR"]
        argv = [str(SSH_BIN), "-F", "/dev/null"] + [item for option in options for item in ("-o", option)]
        return argv + ["127.0.0.1", shlex.join(remote)], "ssh"
    except (OSError, RuntimeError, ValueError):
        return [str(COLIMA_BIN), "ssh", "--profile", PROFILE, "--", *remote], "colima"


class _Observer:
    """A bounded read-only measurement, never a target watchdog or reaper."""
    def __init__(self, control, timeout_s=2.0):
        self.control = control
        # 64 samples: 20 in the first second, the other 44 spread over the rest of a longer run.
        # The guest kill timer outlives the box timer.
        self.guest_timeout = max(6, math.ceil(float(timeout_s)) + 4)
        self.interval = 0.05 if timeout_s <= 2 else round(max(0.05, float(timeout_s) / 44), 2)
        self.ready = threading.Event()
        self.cancel = threading.Event()
        self.thread = None
        self.prefix = bytearray()
        self.result = observation.unknown("collector not started", status="NOT_STARTED")

    def _feed(self, data):
        if not self.ready.is_set():
            self.prefix.extend(data[:max(0, 128-len(self.prefix))])
            if self.prefix.startswith(("ARMED\t" + self.control.cid + "\n").encode()):
                self.ready.set()

    def _work(self, script):
        remote = ["sudo", "/usr/bin/timeout", "-s", "KILL", str(self.guest_timeout), "/bin/sh", "-s", "--", self.control.cid]
        if self.interval != 0.05:
            remote.append(format(self.interval, ".2f"))
        argv, transport = _observer_transport(remote)
        budget = self.guest_timeout + 2.0
        attempt = dict(phase="observe", argv=argv, transport=transport, executed=True,
                       script_sha256=hashlib.sha256(script).hexdigest(), timeout_budget_s=budget,
                       deadline_monotonic=time.monotonic()+budget)
        with self.control.operations_lock:
            self.control.operations.append(attempt)
        try:
            capture = _capture(argv, script, budget, 131072, deadline=attempt["deadline_monotonic"],
                               on_stdout=self._feed, cancel=self.cancel)
            with self.control.operations_lock:
                attempt.update(capture)
            if (capture["returncode"] != 0 or capture["timed_out"] or capture.get("cancelled")
                or not capture["input_complete"] or not capture["output_complete"]
                or capture["stdout_truncated"] or capture["stderr_truncated"] or capture["stderr"]):
                raise RuntimeError("collector transport incomplete or failed")
            self.result = observation.parse(capture["stdout"], self.control.cid)
        except Exception as exc:
            with self.control.operations_lock:
                attempt["error"] = type(exc).__name__ + ": " + str(exc)
            self.result = observation.unknown(attempt["error"])

    def start(self):
        _guard()
        script = Path(__file__).with_name("_observe.sh").read_bytes()
        if len(script) > 8192:
            raise RuntimeError("collector script exceeds fixed bound")
        self.thread = threading.Thread(target=self._work, args=(script,), daemon=True)
        self.thread.start()
        if not self.ready.wait(1.0):
            raise RuntimeError("trusted collector did not arm before START")

    def finish(self):
        if self.thread is not None:
            try:
                self.thread.join(1.0)
            finally:
                self.cancel.set()
                self.thread.join(1.1)
            if self.thread.is_alive():
                self.result = observation.unknown("collector client shutdown unconfirmed")
        return self.result


def _check_policy(data, timeout_s=2.0, box=None):
    box = box or STDLIB_BOX
    c, h = data["Config"], data["HostConfig"]
    expected = dict(NetworkMode="none", ReadonlyRootfs=True, Privileged=False, Memory=box.memory,
                    MemorySwap=box.memory, PidsLimit=box.pids, NanoCpus=box.nano_cpus, CapDrop=["ALL"])
    if any(h.get(k) != v for k, v in expected.items()):
        raise RuntimeError("container defensive HostConfig does not match the fixed baseline")
    if (c.get("Image") != box.ref or c.get("User") != "10000:10000" or c.get("Tty") is not False
        or c.get("OpenStdin") is not True or c.get("Entrypoint") != ["timeout"] or c.get("Cmd") != _timer_args(timeout_s, box)
        or h.get("Init") not in (None, False) or h.get("PidMode") not in (None, "")
        or h.get("IpcMode") not in (None, "private") or h.get("RestartPolicy", {}).get("Name") != "no"
        or h.get("SecurityOpt") not in (["no-new-privileges"], ["no-new-privileges:true"])
        or h.get("Tmpfs") != {"/tmp": box.tmpfs} or h.get("LogConfig", {}).get("Type") != "none"
        or h.get("Ulimits") != [{"Name": "nofile", "Hard": 128, "Soft": 128}]
        or h.get("Binds") or h.get("Mounts") or h.get("PortBindings")
        or h.get("CapAdd") or h.get("Devices") or h.get("DeviceRequests")
        or h.get("VolumesFrom") or h.get("ExtraHosts") or h.get("PublishAllPorts")
        or any(m.get("Type") != "tmpfs" or m.get("Destination") != "/tmp" for m in data["Mounts"])):
        raise RuntimeError("container image/user/stdio/mount/security baseline mismatch")


class _Control:
    def __init__(self, identity, cid=None):
        labels = identity["labels"]
        if (set(identity) != {"name", "labels"} or set(labels) != {"io.pybox.owner", "io.pybox.run", "io.pybox.expires"}
            or not re.fullmatch(r"[0-9a-f]{32}", labels["io.pybox.owner"])
            or not re.fullmatch(r"[0-9a-f]{32}", labels["io.pybox.run"])
            or not re.fullmatch(r"[1-9][0-9]{9,}", labels["io.pybox.expires"])
            or identity["name"] != "pybox-step3-" + labels["io.pybox.run"]
            or cid is not None and not re.fullmatch(r"[0-9a-f]{64}", cid)):
            raise ValueError("invalid controlled run identity")
        self.identity = identity
        self.cid = cid
        self.inspection = None
        self.operations = []
        self.operations_lock = threading.Lock()
        self.timeouts = []
        self.errors = []
        self.cleanup_status = "UNCONFIRMED"
        self.create_rejected = False

    def command(self, phase, args, *, input_data=None, cap=65536, deadline=None, limit=None, budget=None):
        _guard()
        started = time.monotonic()
        budget = OPERATION_TIMEOUTS[phase] if budget is None else budget
        own_deadline = started + budget
        end = min(own_deadline, deadline) if deadline is not None else own_deadline
        timeout_kind = limit if deadline is not None and deadline <= own_deadline else phase
        if end <= started:
            if timeout_kind not in self.timeouts:
                self.timeouts.append(timeout_kind)
            self.operations.append(dict(phase=phase, argv=PREFIX + args, executed=False, timed_out=True,
                                        timeout_kind=timeout_kind, deadline_monotonic=end))
            raise TimeoutError(timeout_kind + " budget exhausted before " + phase)
        attempt = dict(phase=phase, argv=PREFIX + args, executed=True,
                       start_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), deadline_monotonic=end)
        self.operations.append(attempt)
        try:
            result = _capture(PREFIX + args, input_data, budget, cap, deadline=end)
        except BaseException as exc:
            attempt.update(error=type(exc).__name__ + ": " + str(exc),
                           end_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
            raise
        # min(): end - started can exceed the budget by a rounding error (5.000000000000007).
        result.update(phase=phase, executed=True, timeout_budget_s=min(budget, end - started), deadline_monotonic=end,
                      timeout_kind=timeout_kind if result["timed_out"] else None)
        attempt.update(result)
        if result["timed_out"] and timeout_kind not in self.timeouts:
            self.timeouts.append(timeout_kind)
        return result

    def metadata(self, phase, args, *, deadline=None, limit=None):
        result = self.command(phase, args, deadline=deadline, limit=limit)
        complete = (not result["timed_out"] and result["output_complete"]
                    and not result["stdout_truncated"] and not result["stderr_truncated"])
        if phase == "create":
            self.create_rejected = (complete and result["returncode"] > 0 and not result["stdout"].strip()
                                    and re.fullmatch(r"Error response from daemon: \S.*", result["stderr"].strip(), re.DOTALL) is not None
                                    and not re.search(r"\b(?:deadline[\s_-]*exceeded|timed?[\s_-]*out|cancel\w*|EOF)\b", result["stderr"], re.IGNORECASE))
        if result["returncode"] != 0 or not complete:
            raise RuntimeError("Docker {} failed (client status {}, timeout {})".format(
                phase, result["returncode"], result["timeout_kind"]))
        return result["stdout"].strip()

    def inspect_owned(self, *, deadline=None, limit=None):
        data = json.loads(self.metadata("inspect", ["container", "inspect", "--format", INSPECT, self.cid],
                                        deadline=deadline, limit=limit))
        if (data["Id"] != self.cid or data["Name"] != "/" + self.identity["name"]
            or any(data["Config"]["Labels"].get(k) != v for k, v in self.identity["labels"].items())):
            raise RuntimeError("container ID/name/owner/run/expiry mismatch; will not touch unrelated object")
        self.inspection = data
        return data

    def cleanup(self):
        deadline = time.monotonic() + CLEANUP_BUDGET_S
        try:
            args = ["container", "ls", "--all", "--quiet", "--no-trunc"]
            if self.cid is not None:
                args += ["--filter", "id=" + self.cid]
            else:
                args += ["--filter", "name=^/" + self.identity["name"] + "$"]
                for k, v in self.identity["labels"].items():
                    args += ["--filter", "label=" + k + "=" + v]
            found = self.metadata("query", args, deadline=deadline, limit="cleanup_budget")
            if found == "":
                if self.cid is None and not self.create_rejected:
                    raise RuntimeError("run is not currently listed, but create completion is unresolved; a late object is possible")
                self.cleanup_status = "NOT_CREATED" if self.cid is None else "ABSENT"
                return
            if not re.fullmatch(r"[0-9a-f]{64}", found) or self.cid is not None and found != self.cid:
                raise RuntimeError("ambiguous run identity query; no object will be removed")
            self.cid = found
            data = self.inspect_owned(deadline=deadline, limit="cleanup_budget")
            if data["State"]["Running"]:
                self.metadata("kill", ["container", "kill", "--signal=KILL", self.cid], deadline=deadline, limit="cleanup_budget")
                data = self.inspect_owned(deadline=deadline, limit="cleanup_budget")
                if data["State"]["Running"] or data["State"]["Status"] != "exited":
                    raise RuntimeError("engine kill did not establish an exited target")
            self.metadata("remove", ["container", "rm", "--force", self.cid], deadline=deadline, limit="cleanup_budget")
            absent = self.metadata("query", ["container", "ls", "--all", "--quiet", "--no-trunc", "--filter", "id=" + self.cid],
                                   deadline=deadline, limit="cleanup_budget")
            if absent != "":
                raise RuntimeError("owned object remains after removal")
            self.cleanup_status = "REMOVED"
        except Exception as exc:
            self.errors.append("owned cleanup UNCONFIRMED: " + str(exc))


def _identity(owner):
    token = uuid.uuid4().hex
    # Keep the established name format so Step 3 leftovers remain discoverable.
    return dict(name="pybox-step3-" + token, labels={"io.pybox.owner": owner, "io.pybox.run": token,
                "io.pybox.expires": str(int(time.time()) + EXPIRY_S)})


def _private_file(fd):
    s = os.fstat(fd)
    if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077 or s.st_nlink != 1:
        raise RuntimeError("unsafe lifecycle state file")


@contextmanager
def _admission():
    """Single-flight admission; kernel releases the lock on supervisor death."""
    _guard()
    fd = os.open(ROOT / "lifecycle.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        _private_file(fd)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another PyBox run or cleanup holds lifecycle admission") from exc
        yield
    finally:
        os.close(fd)


def _attempt_directory():
    path = ROOT / "attempts"
    path.mkdir(mode=0o700, exist_ok=True)
    s = path.lstat()
    if (not stat.S_ISDIR(s.st_mode) or path.resolve() != path or s.st_uid != os.getuid() or s.st_mode & 0o077):
        raise RuntimeError("unsafe attempt directory")
    return path


def _read_attempt(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "r") as file:
        _private_file(file.fileno())
        if os.fstat(file.fileno()).st_size > 4096:
            raise RuntimeError("oversize attempt record")
        data = json.load(file)
    if not isinstance(data, dict) or set(data) != {"version", "identity", "container_id"} or type(data["version"]) is not int or data["version"] != 1:
        raise RuntimeError("invalid attempt record schema")
    control = _Control(data["identity"], data["container_id"])
    if path.name != control.identity["labels"]["io.pybox.run"] + ".json":
        raise RuntimeError("attempt filename/identity mismatch")
    return data


def _save_attempt(identity, cid=None):
    _Control(identity, cid)
    directory = _attempt_directory()
    destination = directory / (identity["labels"]["io.pybox.run"] + ".json")
    if (destination.exists() or destination.is_symlink()) and _read_attempt(destination)["identity"] != identity:
        raise RuntimeError("will not overwrite another attempt")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=directory, prefix=".pending-", delete=False) as file:
            temporary = Path(file.name)
            json.dump(dict(version=1, identity=identity, container_id=cid), file)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _clear_attempt(identity):
    path = _attempt_directory() / (identity["labels"]["io.pybox.run"] + ".json")
    if path.exists() or path.is_symlink():
        if _read_attempt(path)["identity"] != identity:
            raise RuntimeError("attempt identity changed; will not unlink")
        path.unlink()


def _reconcile_owned(owner, resolve=frozenset()):
    """Report every owned object; remove only verified expired, stopped ones.

    Caller holds admission. Never sends KILL and never uses force removal.
    A journal precedes CREATE so an empty lookup cannot hide a late create.
    `resolve` names unacknowledged attempts an operator explicitly asks to
    retire; each still needs expiry + margin and a complete empty identity query.
    """
    control = _Control(_identity(owner))
    deadline = time.monotonic() + CLEANUP_BUDGET_S
    cutoff = int(time.time())
    found, removed, pending, errors = [], [], [], []
    attempts = {}
    observed = set()
    complete = False
    running = False
    try:
        paths = list(islice(_attempt_directory().iterdir(), MAX_RECONCILE_CONTAINERS + 1))
        if len(paths) > MAX_RECONCILE_CONTAINERS:
            raise RuntimeError("too many pending attempt files for bounded reconciliation")
        for path in paths:
            data = _read_attempt(path)
            if data["identity"]["labels"]["io.pybox.owner"] != owner:
                raise RuntimeError("foreign owner in local attempt journal")
            attempts[data["identity"]["labels"]["io.pybox.run"]] = data
        ids = control.metadata("query", ["container", "ls", "--all", "--quiet", "--no-trunc",
                               "--filter", "label=io.pybox.owner=" + owner], deadline=deadline, limit="cleanup_budget").split()
        if len(ids) > MAX_RECONCILE_CONTAINERS or len(set(ids)) != len(ids) or any(not re.fullmatch(r"[0-9a-f]{64}", cid) for cid in ids):
            raise RuntimeError("ambiguous or excessive owned container listing")
        for cid in ids:
            item = dict(container_id=cid, status="UNCONFIRMED")
            found.append(item)
            try:
                raw = json.loads(control.metadata("inspect", ["container", "inspect", "--format", INSPECT, cid],
                                                 deadline=deadline, limit="cleanup_budget"))
                labels = raw["Config"]["Labels"]
                identity = dict(name=raw["Name"].removeprefix("/"), labels={k: labels[k] for k in
                                ["io.pybox.owner", "io.pybox.run", "io.pybox.expires"]})
                _Control(identity, cid)
                if raw["Id"] != cid or raw["Name"] != "/" + identity["name"] or labels["io.pybox.owner"] != owner:
                    raise RuntimeError("owned listing/inspection identity mismatch")
                token = labels["io.pybox.run"]
                attempt = attempts.get(token)
                if attempt and (attempt["identity"] != identity or attempt["container_id"] not in (None, cid)):
                    raise RuntimeError("journal and engine identity disagree")
                observed.add(token)
                item.update(identity=identity, state=raw["State"], expiry=int(labels["io.pybox.expires"]))
                running |= bool(raw["State"]["Running"])
                if item["expiry"] > cutoff:
                    item["status"] = "KEPT_UNEXPIRED"
                    continue
                control.identity, control.cid = identity, cid
                current = control.inspect_owned(deadline=deadline, limit="cleanup_budget")
                if current["State"]["Running"] or current["State"]["Status"] not in {"created", "exited", "dead"}:
                    raise RuntimeError("expired object is not confirmed stopped; no kill or force removal")
                if item["expiry"] > int(time.time()):
                    raise RuntimeError("calendar clock moved behind expiry; keeping object")
                control.metadata("remove", ["container", "rm", cid], deadline=deadline, limit="cleanup_budget")
                absent = control.metadata("query", ["container", "ls", "--all", "--quiet", "--no-trunc", "--filter", "id=" + cid],
                                          deadline=deadline, limit="cleanup_budget")
                if absent:
                    raise RuntimeError("absence after removal not established")
                item["status"] = "REMOVED"
                removed.append(cid)
                if attempt:
                    _clear_attempt(identity)
            except Exception as exc:
                item["error"] = str(exc)
                errors.append(cid + ": " + str(exc))
        for token, attempt in attempts.items():
            if token in observed:
                continue
            item = dict(identity=attempt["identity"], container_id=attempt["container_id"], status="UNCONFIRMED")
            pending.append(item)
            cid = attempt["container_id"]
            if cid is not None:
                absent = control.metadata("query", ["container", "ls", "--all", "--quiet", "--no-trunc", "--filter", "id=" + cid],
                                          deadline=deadline, limit="cleanup_budget")
                if not absent:
                    _clear_attempt(attempt["identity"])
                    item["status"] = "ABSENT"
                    continue
            elif token in resolve:
                # Operator-requested retirement of an unacknowledged CREATE. A late object
                # would still carry the owner label and be reconciled like any other.
                if int(attempt["identity"]["labels"]["io.pybox.expires"]) + RESOLVE_MARGIN_S > int(time.time()):
                    errors.append("attempt " + token + " is not yet past expiry plus resolution margin")
                    continue
                args = ["container", "ls", "--all", "--quiet", "--no-trunc",
                        "--filter", "name=^/" + attempt["identity"]["name"] + "$"]
                for k, v in attempt["identity"]["labels"].items():
                    args += ["--filter", "label=" + k + "=" + v]
                if control.metadata("query", args, deadline=deadline, limit="cleanup_budget") == "":
                    _clear_attempt(attempt["identity"])
                    item["status"] = "ABSENT_AFTER_EXPIRY"
                    continue
                errors.append("attempt " + token + " identity query is not empty; not resolved")
                continue
            errors.append("unresolved create/identity in attempt journal: " + token + "; a late object is possible")
        complete = True
    except Exception as exc:
        errors.append(str(exc))
        represented = {x["identity"]["labels"]["io.pybox.run"] for x in pending}
        for token, attempt in attempts.items():
            if token not in observed and token not in represented:
                pending.append(dict(identity=attempt["identity"], container_id=attempt["container_id"], status="UNCONFIRMED"))
    return CleanupResult(owner, found, removed, pending, control.operations, complete,
                         complete and not errors and not running, "; ".join(errors) or None)


def cleanup_containers(resolve_attempts=()):
    """Reconcile this installation without executing submitted source or booting a VM.

    `resolve_attempts` lists run tokens of unacknowledged CREATE attempts to retire
    once past expiry plus RESOLVE_MARGIN_S, if a complete identity query is empty.
    """
    try:
        resolve = frozenset(resolve_attempts)
        if any(not isinstance(t, str) or not re.fullmatch(r"[0-9a-f]{32}", t) for t in resolve):
            raise ValueError("resolve_attempts must be 32-hex run tokens")
        with _admission():
            return _reconcile_owned(_installation_owner(), resolve)
    except Exception as exc:
        return CleanupResult(runner_error=str(exc))


def _termination_evidence(inspection, operations, timer_limit_s):
    state = inspection.get("State", {}) if inspection else {}
    kills = [o for o in operations if o.get("phase") == "kill" and o.get("executed")]
    acknowledged = [o for o in kills if o.get("returncode") == 0 and not o.get("timed_out") and o.get("output_complete")]
    result = dict(mechanism="UNKNOWN", pybox_kill_attempted=bool(kills),
                  pybox_kill_sent=True if acknowledged else None if kills else False, timer_limit_s=timer_limit_s,
                  started_at=state.get("StartedAt"), finished_at=state.get("FinishedAt"),
                  exitcode=state.get("ExitCode"), oom_killed=state.get("OOMKilled"))
    try:
        start = datetime.datetime.fromisoformat(state["StartedAt"].replace("Z", "+00:00"))
        finish = datetime.datetime.fromisoformat(state["FinishedAt"].replace("Z", "+00:00"))
        if start.year == 1 or finish.year == 1 or finish < start or state["Running"] or state["Status"] != "exited" or state["Error"]:
            return result
        lifetime = (finish - start).total_seconds()
        result["engine_lifetime_s"] = lifetime
        if state["ExitCode"] == 137:
            if not state.get("OOMKilled") and acknowledged and any(start <= datetime.datetime.fromisoformat(o["start_utc"]) <= finish for o in acknowledged):
                result["mechanism"] = "SUPERVISOR_KILL_OBSERVED"
            elif not state.get("OOMKilled") and not kills and timer_limit_s <= lifetime <= timer_limit_s + 1.0:
                result["mechanism"] = "IN_CONTAINER_TIMER_CONSISTENT"
        elif not kills:
            result["mechanism"] = "TARGET_EXIT_OBSERVED"
    except (KeyError, TypeError, ValueError):
        pass
    return result


def run_container(source: str, *, timeout_s: float = 2.0, max_output_bytes: int = 65536,
                  image: str = "stdlib", inputs=(), collect_outputs: bool = False) -> ContainerResult:
    """Run one program in a fresh box. The defaults are the qualified M3–M5 box.

    Opt-in per run: `image` ("data" adds numpy/pandas), `timeout_s` up to 30,
    `inputs` as (name, bytes) copies under /tmp/input, and `collect_outputs` to bring
    back what the program writes under /tmp/output (untrusted, bounded, in memory).
    """
    if not isinstance(source, str):
        raise ValueError("source must be a UTF-8 string of at most 65536 bytes")
    encoded = source.encode("utf-8")
    if len(encoded) > MAX_SOURCE_BYTES:
        raise ValueError("source must be a UTF-8 string of at most 65536 bytes")
    if (isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float))
            or not 0 < timeout_s <= boxes.MAX_TIMEOUT_S or not math.isfinite(timeout_s)):
        raise ValueError("timeout_s must be finite, greater than zero and at most {:g} seconds".format(boxes.MAX_TIMEOUT_S))
    if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int) or not 1 <= max_output_bytes <= 65536:
        raise ValueError("max_output_bytes must be an integer from 1 to 65536 per stream")
    inputs = boxes.check_files(inputs, "input")
    # The bootstrap carries files and the final-reading linger; the default box never uses it.
    files = boxes.opt_in(image, bool(inputs) or bool(collect_outputs), timeout_s)
    linger = boxes.linger_for(timeout_s) if files else 0.0
    boundary = uuid.uuid4().hex
    stdin_data = boxes.frame(encoded, inputs, collect_outputs, boundary, linger, timeout_s) if files else encoded
    capture_cap = max_output_bytes + (boxes.OUTPUT_WIRE_CAP if collect_outputs else 0)
    box = None
    output_files, outputs_skipped, outputs_error = [], [], None
    lifecycle_start = time.monotonic()
    control = None
    attached = None
    wall_start = None
    wall_deadline = None
    create_attempted = False
    start_attempted = False
    errors = []
    admission = None
    admitted = False
    reconciliation = None
    observer = None
    resources = observation.unknown("target was not started", status="NOT_STARTED")
    policy_verified = False
    cancelled = False
    phase = "admission"
    try:
        admission = _admission()
        admission.__enter__()
        admitted = True
        owner = _installation_owner()
        reconciled = _reconcile_owned(owner)
        reconciliation = asdict(reconciled)
        if not reconciled.admission_allowed:
            raise RuntimeError("reconciliation blocks execution: " + (reconciled.runner_error or "an owned target is still running"))
        phase = "image"
        box = resolve_box(image, files, moves_files=bool(inputs) or bool(collect_outputs))
        identity = _identity(owner)
        control = _Control(identity)
        _save_attempt(identity)
        create_attempted = True
        phase = "create"
        created = control.metadata("create", _create_args(identity, timeout_s, box))
        if not re.fullmatch(r"[0-9a-f]{64}", created):
            raise RuntimeError("Docker create did not return one full container ID")
        control.cid = created
        _save_attempt(identity, created)
        inspection = control.inspect_owned()
        phase = "policy"
        _check_policy(inspection, timeout_s, box)
        policy_verified = True
        if inspection["State"]["Status"] != "created" or inspection["State"]["Running"]:
            raise RuntimeError("new fixture was not stopped before attachment/start")
        _guard()
        phase = "collector_arm"
        observer = _Observer(control, timeout_s)
        observer.start()
        phase = "start"
        start_attempted = True
        wall_start = time.monotonic()
        wall_deadline = wall_start + float(timeout_s)
        attached = control.command("start", ["container", "start", "--attach", "--interactive", control.cid],
                                   input_data=stdin_data, cap=capture_cap, deadline=wall_deadline, limit="wall",
                                   budget=max(OPERATION_TIMEOUTS["start"], float(timeout_s)))
        if collect_outputs:
            program, output_files, outputs_skipped, outputs_error = boxes.split_outputs(attached["stdout"], boundary)
            data = program.encode("utf-8", errors="surrogatepass")
            if len(data) > max_output_bytes:
                program = data[:max_output_bytes].decode("utf-8", errors="ignore")
                attached["stdout_truncated"] = True
            attached["stdout"] = program
            with control.operations_lock:
                for op in control.operations:
                    if op.get("phase") == "start":
                        op.update(stdout=program, stdout_truncated=attached["stdout_truncated"],
                                  output_transfer=dict(files=len(output_files), error=outputs_error))
        if time.monotonic() >= wall_deadline:
            if "wall" not in control.timeouts:
                control.timeouts.append("wall")
        if "wall" not in control.timeouts:
            # The wall bounds execution; post-exit metadata has its own inspect budget.
            inspection = control.inspect_owned()
            _check_policy(inspection, timeout_s, box)
            state = inspection["State"]
            if not attached["input_complete"] or not attached["output_complete"]:
                errors.append("source/output transport incomplete")
            if state["Status"] != "exited" or state["Running"] or state["Error"] or attached["returncode"] != state["ExitCode"]:
                errors.append("engine/transport state differs from a completed target exit")
    except KeyboardInterrupt:
        cancelled = True
        errors.append("execution cancelled by caller")
    except Exception as exc:
        errors.append(str(exc))
    finally:
        try:
            if control is not None and create_attempted:
                # A first interrupt during cleanup is recorded and cleanup is retried
                # once, as in the native runner; a second interrupt propagates.
                try:
                    control.cleanup()
                except KeyboardInterrupt:
                    cancelled = True
                    errors.append("cleanup interrupted by caller; retried once")
                    control.cleanup()
                errors.extend(control.errors)
                try:
                    if control.cleanup_status in {"REMOVED", "ABSENT", "NOT_CREATED"}:
                        _clear_attempt(control.identity)
                    else:
                        _save_attempt(control.identity, control.cid)
                except Exception as exc:
                    errors.append("attempt journal: " + str(exc))
        finally:
            try:
                if observer is not None:
                    resources = observer.finish()
            finally:
                if admitted:
                    admission.__exit__(None, None, None)
    inspection = control.inspection if control else None
    state = inspection["State"] if inspection else {}
    # A client whose shutdown is unconfirmed must not rewrite returned evidence.
    if control:
        with control.operations_lock:
            operations = copy.deepcopy(control.operations)
    else:
        operations = []
    result = ContainerResult(
        backend="container", stdout=attached["stdout"] if attached else "", stderr=attached["stderr"] if attached else "",
        returncode=state.get("ExitCode") if start_attempted and state.get("Status") == "exited" and not state.get("Running")
        and not state.get("Error") and state.get("StartedAt") and not state["StartedAt"].startswith("0001-") else None,
        elapsed_s=attached["elapsed_s"] if attached else 0.0, timed_out=bool(control and control.timeouts),
        stdout_truncated=bool(attached and attached["stdout_truncated"]), stderr_truncated=bool(attached and attached["stderr_truncated"]),
        output_complete=bool(attached and attached["output_complete"]), runner_error="; ".join(errors) or None,
        container_id=control.cid if control else None,
        removed=bool(control and control.cleanup_status in {"ABSENT", "REMOVED"}), inspection=inspection,
        operations=operations, identity=control.identity if control else None,
        cleanup_status=control.cleanup_status if control and create_attempted else "NOT_ATTEMPTED",
        timeouts=control.timeouts if control else [],
        wall_start_monotonic=wall_start, wall_deadline_monotonic=wall_deadline,
        lifecycle_elapsed_s=time.monotonic() - lifecycle_start,
        timer_limit_s=float(timeout_s) + TIMER_MARGIN_S,
        termination_evidence=_termination_evidence(inspection, operations, float(timeout_s) + TIMER_MARGIN_S),
        reconciliation=reconciliation,
        resources=resources, cancelled=cancelled, image=image, inputs=boxes.describe(inputs),
        outputs=boxes.describe(output_files), outputs_skipped=outputs_skipped,
        outputs_error=outputs_error if collect_outputs and start_attempted else None, output_files=tuple(output_files),
    )
    if box is None:
        # The image never resolved; the record still names what was asked for.
        try:
            box = boxes.make_box("stdlib", IMAGE, files) if image == "stdlib" else boxes.make_box(image, "unresolved", files)
        except ValueError:
            box = boxes.make_box("stdlib", IMAGE, files)
    record = make_record(result, image=box.ref, source_sha256=hashlib.sha256(encoded).hexdigest(), timeout_s=timeout_s,
                         cap=max_output_bytes, policy_verified=policy_verified, phase=phase, box=box,
                         collect_outputs=bool(collect_outputs), linger_s=linger)
    return ContainerResult(**{**result.__dict__, "record": record})
