"""Consent-gated creation and operation of the dedicated restricted runtime.

Nothing here installs software, and nothing runs without an explicit command.
`setup` is a dry run unless `yes=True`; existing files are verified, never
overwritten. Paths, policy and tool locations come from `container`, so the
engine's guard and this module always agree.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
import uuid

from . import boxes, container

START_ARGS = ["start", container.PROFILE, "--runtime", "docker", "--vm-type", "vz", "--arch", "aarch64",
              "--cpus", "2", "--memory", "2", "--disk", "20", "--root-disk", "20", "--mount=none",
              "--port-forwarder=none", "--activate=false", "--ssh-config=false", "--ssh-agent=false",
              "--kubernetes=false", "--vz-rosetta=false", "--binfmt=false"]
DOCKER_CONFIG_DATA = {"auths": {"https://index.docker.io/v1/": {}}, "credsStore": "", "credHelpers": {}}
TIMEOUTS = dict(list=20.0, start=900.0, stop=120.0, pull=900.0, inspect=20.0, build=900.0, commit=120.0, remove=60.0)
OPTIONAL_IMAGES = tuple(name for name in boxes.PROFILES if name != "stdlib")
# Profile readback after start: no host mounts, no port forwarder, no VM address, not activated.
PROFILE_POLICY = [r"(?m)^mounts: (null|\[\])$", r"(?m)^portForwarder: none$",
                  r"(?m)^  address: false$", r"(?m)^autoActivate: false$"]


def _dirs():
    r = container.ROOT
    return [r.parent, r, container.COLIMA, container.LIMA, container.LIMA / "_config", container.DOCKER_CONFIG,
            r / "cache", r / "cache/colima", r / "cache/colima/caches", r / "tmp", r / "logs"]


def _files():
    return [(container.LIMA / "_config/override.yaml", container.POLICY),
            (container.DOCKER_CONFIG / "config.json", json.dumps(DOCKER_CONFIG_DATA))]


def _run(argv, timeout):
    # Colima creates profile directories as the caller; keep them private.
    previous = os.umask(0o077)
    try:
        result = container._capture(argv, None, timeout, 1048576)
    finally:
        os.umask(previous)
    ok = (result["returncode"] == 0 and not result["timed_out"] and result["output_complete"]
          and not result["stdout_truncated"] and not result["stderr_truncated"])
    return ok, result


def _private_dir(path):
    s = path.lstat()
    return (stat.S_ISDIR(s.st_mode) and not path.is_symlink() and path.resolve() == path
            and s.st_uid == os.getuid() and not s.st_mode & 0o077)


def _file_matches(path, content):
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode) or path.is_symlink() or s.st_uid != os.getuid() or s.st_mode & 0o022:
        return False
    text = path.read_text()
    if path.suffix == ".json":
        return json.loads(text) == json.loads(content)
    return text == content


def profile_status():
    """The profile's Colima status ('Running', 'Stopped', …) or None when absent."""
    ok, result = _run([str(container.COLIMA_BIN), "list", "--json"], TIMEOUTS["list"])
    if not ok:
        raise RuntimeError("colima list failed: " + result["stderr"][-300:])
    for line in result["stdout"].splitlines():
        if line.strip():
            data = json.loads(line)
            if data.get("name") == container.PROFILE:
                return data.get("status")
    return None


def _image_check():
    ok, result = _run(container.PREFIX + ["image", "inspect", container.IMAGE, "--format",
                                          "{{json .RepoDigests}} {{.Id}} {{.Os}}/{{.Architecture}}"], TIMEOUTS["inspect"])
    if not ok:
        return False
    digests, offset = json.JSONDecoder().raw_decode(result["stdout"].strip())
    image_id, plat = result["stdout"].strip()[offset:].split()
    return container.IMAGE in digests and image_id == container.IMAGE.split("@")[1] and plat == "linux/arm64"


def _profile_policy():
    text = (container.COLIMA / container.PROFILE / "colima.yaml").read_text()
    missing = [p for p in PROFILE_POLICY if not re.search(p, text)]
    if missing:
        raise RuntimeError("profile configuration differs from the restricted baseline: " + ", ".join(missing))


def plan():
    """What setup would do, as (state, description) pairs. Reads only."""
    container._check_platform()
    steps = []
    for tool in (container.DOCKER_BIN, container.COLIMA_BIN):
        try:
            container._check_tool(tool)
            steps.append(("ok", "tool " + str(tool)))
        except RuntimeError as exc:
            steps.append(("missing", str(exc)))
    for path in _dirs():
        if not os.path.lexists(path):
            steps.append(("create", "private directory (0700) " + str(path)))
        elif not _private_dir(path):
            steps.append(("conflict", "existing path is not a private directory: " + str(path)))
        else:
            steps.append(("ok", "directory " + str(path)))
    for path, content in _files():
        if not os.path.lexists(path):
            steps.append(("create", "file (0600) " + str(path)))
        elif not _file_matches(path, content):
            steps.append(("conflict", "existing file differs; will not overwrite: " + str(path)))
        else:
            steps.append(("ok", "file " + str(path)))
    return steps


def _elapsed(start):
    seconds = int(time.monotonic() - start)
    return "{} min {} s".format(seconds // 60, seconds % 60) if seconds >= 60 else "{} s".format(seconds)


def setup(yes=False, out=print, with_images=()):
    """Create the dedicated runtime. Dry run unless yes=True. Returns a CLI status.

    `with_images` adds optional images (for example "data") built inside the VM from
    the recipe shipped with PyBox; the VM is left as it was found.
    """
    began = time.monotonic()
    with_images = tuple(dict.fromkeys(with_images))
    unknown = [n for n in with_images if n not in OPTIONAL_IMAGES]
    if unknown:
        out("unknown image: " + ", ".join(unknown) + " (available: " + ", ".join(OPTIONAL_IMAGES) + ")")
        return 2
    steps = plan()
    for state, text in steps:
        out("{:<9} {}".format(state, text))
    if any(s == "missing" for s, _ in steps):
        out("\nInstall the prerequisites first:  brew install colima docker   (PyBox never installs software)")
        return 2
    if any(s == "conflict" for s, _ in steps):
        out("\nSetup stopped: resolve the conflicts above by hand. Nothing was changed.")
        return 2
    existing = profile_status()
    if existing is not None:
        out("\nVM profile '{}' already exists ({}). Setup will not change or re-pull the base image.".format(container.PROFILE, existing))
        if not with_images:
            out("Check it with:  pybox doctor   (start it first with: pybox vm start)")
            if yes:
                _create_tree(out)
            return 0
        out("It will build: " + ", ".join(with_images) + " (" + _image_note() + ")")
        if not yes:
            out("\nDry run: nothing was changed. Run `pybox setup --yes --with {}` to do this.".format(" --with ".join(with_images)))
            return 0
        _create_tree(out)
        _check_files_unchanged()
        started_here = existing != "Running"
        if started_here:
            out("starting VM profile…")
            ok, result = _run([str(container.COLIMA_BIN)] + START_ARGS, TIMEOUTS["start"])
            if not ok:
                out("VM start failed: " + result["stderr"][-500:])
                return 125
        try:
            _profile_policy()
            container._guard()
            if not _image_check():
                raise RuntimeError("pinned base image missing")
            for name in with_images:
                build_image(name, out)
            out("done in " + _elapsed(began))
            return 0
        except Exception as exc:
            out("image build failed: " + str(exc))
            return 125
        finally:
            if started_here:
                ok, _ = _run([str(container.COLIMA_BIN), "stop", container.PROFILE], TIMEOUTS["stop"])
                out("VM stopped" if ok else "VM stop failed; run: pybox vm stop")
    out("\nThen: start the dedicated VM profile '{}' once (first run downloads Colima's VM image, ~330 MB),".format(container.PROFILE))
    out("pull only the pinned image {} for linux/arm64 from Docker Hub,".format(container.IMAGE))
    out("verify it, and stop the VM. No host folders are shared and no ports are forwarded.")
    if with_images:
        out("Also build: " + ", ".join(with_images) + " (" + _image_note() + ")")
    if not yes:
        out("\nDry run: nothing was changed. Run `pybox setup --yes` to do this.")
        return 0
    _create_tree(out)
    out("starting VM profile (this can take several minutes)…")
    ok, result = _run([str(container.COLIMA_BIN)] + START_ARGS, TIMEOUTS["start"])
    if not ok:
        out("VM start failed: " + result["stderr"][-500:])
        return 125
    try:
        _profile_policy()
        container._guard()
        if not _image_check():
            out("pulling pinned image…")
            ok, result = _run(container.PREFIX + ["pull", "--platform", "linux/arm64", container.IMAGE], TIMEOUTS["pull"])
            if not ok or not _image_check():
                out("pinned image pull/verification failed: " + result["stderr"][-500:])
                return 125
        out("verified: profile policy, engine guard, pinned image")
        for name in with_images:
            build_image(name, out)
        out("\nSetup finished in {}. Next:\n  pybox vm start\n  echo 'print(6*7)' | pybox exec -".format(_elapsed(began)))
        return 0
    except Exception as exc:
        out("verification failed: " + str(exc))
        return 125
    finally:
        ok, result = _run([str(container.COLIMA_BIN), "stop", container.PROFILE], TIMEOUTS["stop"])
        out("VM stopped" if ok else "VM stop failed; run: pybox vm stop")


def _image_note():
    packages = boxes.recipe_packages()
    return "packages: " + ", ".join("{}=={}".format(k, v) for k, v in packages.items()) + "; downloads about 30 MB from PyPI"


def _write_private(path, data):
    """Atomically replace a private (0600) file in an existing private folder."""
    previous = os.umask(0o077)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=".pending-", delete=False) as file:
            temporary = Path(file.name)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        temporary = None
    finally:
        os.umask(previous)
        if temporary is not None and temporary.exists():
            temporary.unlink()


@contextmanager
def _image_lock():
    """One image build or removal at a time, so images.json is never written from a stale copy."""
    fd = os.open(container.ROOT / "images.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        container._private_file(fd)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another image build or removal is running") from exc
        yield
    finally:
        os.close(fd)


def _remove_stale_builders(out):
    """Remove stopped build containers this installation left behind (for example after a crash)."""
    owner = container._installation_owner()
    ok, result = _run(container.PREFIX + ["container", "ls", "--all", "--no-trunc", "--format", "{{.ID}} {{.State}}",
                                          "--filter", "label=io.pybox.build-owner=" + owner], TIMEOUTS["inspect"])
    for line in result["stdout"].splitlines() if ok else []:
        cid, _, state = line.partition(" ")
        if re.fullmatch(r"[0-9a-f]{64}", cid) and state in ("created", "exited", "dead"):
            _run(container.PREFIX + ["container", "rm", cid], TIMEOUTS["remove"])
            out("removed a leftover build container")


def _write_images(images):
    _write_private(container.IMAGES_FILE, json.dumps(dict(version=1, images=images), indent=2, sort_keys=True))


def _save_recipe(name, lock):
    folder = container.RECIPES
    if not os.path.lexists(folder):
        folder.mkdir(mode=0o700)
    if folder.is_symlink() or not _private_dir(folder):
        raise RuntimeError("unsafe recipes folder: {}".format(folder))
    _write_private(folder / (name + ".lock"), lock)


def _local_image_present(image_id):
    ok, result = _run(container.PREFIX + ["image", "inspect", image_id, "--format", "{{.Id}} {{.Os}}/{{.Architecture}}"],
                      TIMEOUTS["inspect"])
    return ok and result["stdout"].split() == [image_id, "linux/arm64"]


def build_image(name, out=print, lock=None):
    """Build an image in the running VM: install the hash-locked wheels into a throwaway
    container from the pinned base, commit it, and record the resulting ID.

    "data" uses the recipe shipped with PyBox; any other name needs `lock`, a file of
    exact pins with hashes (see boxes.check_lock). This is the only time a PyBox
    container has the network; runs never do.
    """
    boxes.check_image_name(name)
    if name in boxes.BUILT_IN and name != "data":
        raise ValueError("'{}' is built in and can't be rebuilt".format(name))
    with _image_lock():
        return _build_image(name, out, lock)


def _build_image(name, out, lock):
    if name == "data":
        if lock is not None:
            raise ValueError("'data' is built in; give your own image another name")
        lock_text = boxes.recipe_text()
        recipe = boxes.recipe_sha256(container.IMAGE)
    else:
        if lock is None:
            raise ValueError("image '{}' needs a lock file (--lock FILE)".format(name))
        lock_text = boxes.check_lock(lock)
        recipe = boxes.recipe_sha256(container.IMAGE, lock_text)
    images = container.local_images()
    entry = images.get(name)
    if entry and entry["recipe_sha256"] == recipe and _local_image_present(entry["id"]):
        out("image '{}' already built: {}".format(name, entry["id"]))
        return entry
    _remove_stale_builders(out)
    builder = "pybox-build-" + uuid.uuid4().hex
    owner = container._installation_owner()
    install = ("cat > /tmp/requirements.txt && PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INPUT=1 pip install "
               "--no-cache-dir --only-binary=:all: --require-hashes -r /tmp/requirements.txt && rm /tmp/requirements.txt")
    out("building image '{}' (installing pinned wheels; this needs the internet once)…".format(name))
    try:
        ok, result = _run(container.PREFIX + ["container", "create", "--name", builder, "--label", "io.pybox.build=" + name,
                                              "--label", "io.pybox.build-owner=" + owner,
                                              "--pull=never", "--platform=linux/arm64", "--interactive",
                                              "--entrypoint=sh", container.IMAGE, "-c", install], TIMEOUTS["inspect"])
        if not ok:
            raise RuntimeError("build container create failed: " + result["stderr"][-300:])
        previous = os.umask(0o077)
        try:
            result = container._capture(container.PREFIX + ["container", "start", "--attach", "--interactive", builder],
                                        lock_text.encode(), TIMEOUTS["build"], 1048576)
        finally:
            os.umask(previous)
        if result["returncode"] != 0 or result["timed_out"]:
            raise RuntimeError("package install failed: " + (result["stderr"] or result["stdout"])[-500:])
        changes = [item for change in boxes.DATA_CHANGES for item in ("--change", change)]
        # A tag keeps the image from looking dangling (and from `docker image prune`); runs use its ID.
        tag = "pybox-{}:{}".format(name, recipe[:12])
        ok, result = _run(container.PREFIX + ["container", "commit", *changes, builder, tag], TIMEOUTS["commit"])
        image_id = result["stdout"].strip()
        if not ok or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) or not _local_image_present(image_id):
            raise RuntimeError("commit failed: " + result["stderr"][-300:])
    finally:
        ok, _ = _run(container.PREFIX + ["container", "rm", "--force", builder], TIMEOUTS["remove"])
        if not ok:
            out("warning: could not remove build container {}; remove it with docker rm".format(builder))
    entry = dict(id=image_id, base=container.IMAGE, recipe_sha256=recipe, packages=boxes.recipe_packages(lock_text),
                 built_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    if name != "data":
        _save_recipe(name, lock_text)
    images = container.local_images()  # re-read under the lock, just before writing
    images[name] = entry
    _write_images(images)
    out("built image '{}': {}".format(name, image_id))
    return entry


def list_images():
    """(name, state, entry) for every image this installation knows, built-in first."""
    rows = [("stdlib", "built in (pinned digest)", dict(id=container.IMAGE, packages={}))]
    for name, entry in sorted(container.local_images().items()):
        try:
            state = "ok" if entry["recipe_sha256"] == container.expected_recipe(name) else "built from an older recipe"
        except RuntimeError as exc:
            state = str(exc)
        rows.append((name, state, entry))
    return rows


def remove_image(name, out=print):
    """Forget an image and remove it from the running VM. stdlib can't be removed."""
    boxes.check_image_name(name)
    with _image_lock():
        _remove_image(name, out)


def _remove_image(name, out):
    images = container.local_images()
    entry = images.pop(name, None)
    if entry is None:
        raise RuntimeError("image '{}' is not installed".format(name))
    container._guard()
    ok, result = _run(container.PREFIX + ["image", "rm", entry["id"]], TIMEOUTS["remove"])
    if not ok and "No such image" not in result["stderr"]:
        raise RuntimeError("could not remove image: " + result["stderr"][-300:])
    _write_images(images)
    recipe = container.RECIPES / (name + ".lock")
    if recipe.is_file() and not recipe.is_symlink():
        recipe.unlink()
    out("removed image '{}'".format(name))


def _create_tree(out):
    previous = os.umask(0o077)
    try:
        for path in _dirs():
            if not os.path.lexists(path):
                path.mkdir(mode=0o700)
                out("created " + str(path))
        for path, content in _files():
            if not os.path.lexists(path):
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "w") as file:
                    file.write(content)
                out("created " + str(path))
    finally:
        os.umask(previous)


def vm(action, out=print):
    """start | stop | status for the dedicated profile only. Returns a CLI status."""
    container._check_platform()
    container._check_tool(container.COLIMA_BIN)
    status = profile_status()
    if status is None:
        out("No '{}' profile. Run: pybox setup".format(container.PROFILE))
        return 2
    if action == "status":
        out(status)
        return 0
    if action == "stop":
        ok, result = _run([str(container.COLIMA_BIN), "stop", container.PROFILE], TIMEOUTS["stop"])
        out("Stopped" if ok else "stop failed: " + result["stderr"][-300:])
        return 0 if ok else 125
    _check_files_unchanged()
    ok, result = _run([str(container.COLIMA_BIN)] + START_ARGS, TIMEOUTS["start"])
    if not ok:
        out("start failed: " + result["stderr"][-300:])
        return 125
    try:
        _profile_policy()
        container._guard()
        if not _image_check():
            raise RuntimeError("pinned image missing; PyBox will not pull outside setup")
    except Exception as exc:
        out("started, but verification failed: {} — stopping".format(exc))
        _run([str(container.COLIMA_BIN), "stop", container.PROFILE], TIMEOUTS["stop"])
        return 125
    try:
        for name, entry in container.local_images().items():
            if not _local_image_present(entry["id"]):
                out("note: image '{0}' is missing from the VM; rebuild with: pybox setup --yes --with {0}".format(name))
    except RuntimeError as exc:
        out("note: " + str(exc))
    out("Running and verified. Note: the next `pybox exec` or `pybox cleanup` reconciles this installation's expired leftovers.")
    return 0


def _check_files_unchanged():
    for path, content in _files():
        if not os.path.lexists(path) or not _file_matches(path, content):
            raise RuntimeError("runtime file missing or changed: {} (run pybox setup)".format(path))


def doctor():
    """Read-only report; touches no containers and never starts the VM."""
    report = dict(platform=None, tools={}, runtime={}, vm=None, guard=None, image_cached=None, images={}, pending_attempts=None)
    try:
        container._check_platform()
        report["platform"] = "ok"
    except RuntimeError as exc:
        report["platform"] = str(exc)
        return report
    for tool in (container.DOCKER_BIN, container.COLIMA_BIN):
        try:
            report["tools"][str(tool)] = str(container._check_tool(tool))
        except RuntimeError as exc:
            report["tools"][str(tool)] = "ERROR: " + str(exc)
    report["runtime"] = {text: state for state, text in plan() if state != "ok"} or "ok"
    try:
        report["vm"] = profile_status()
    except Exception as exc:
        report["vm"] = "ERROR: " + str(exc)
    try:
        container._guard()
        report["guard"] = "ok"
        report["image_cached"] = _image_check()
        report["images"]["stdlib"] = "ok" if report["image_cached"] else "missing"
    except Exception as exc:
        report["guard"] = str(exc)
    try:
        installed = container.local_images()
        for name in list(OPTIONAL_IMAGES) + sorted(set(installed) - set(OPTIONAL_IMAGES)):
            entry = installed.get(name)
            if entry is None:
                report["images"][name] = "not installed (pybox setup --yes --with {})".format(name)
            elif entry["recipe_sha256"] != container.expected_recipe(name):
                report["images"][name] = "built from an older recipe (rebuild: {})".format(container._rebuild_hint(name))
            elif report["guard"] == "ok":
                report["images"][name] = "ok" if _local_image_present(entry["id"]) else "missing from VM"
            else:
                report["images"][name] = "recorded (VM not running)"
    except Exception as exc:
        report["images"]["error"] = str(exc)
    attempts = container.ROOT / "attempts"
    if attempts.is_dir():
        report["pending_attempts"] = sorted(p.stem for p in attempts.iterdir() if p.suffix == ".json")
    return report


def doctor_ok(report):
    return (report.get("platform") == "ok" and report.get("runtime") == "ok" and report.get("guard") == "ok"
            and report.get("image_cached") is True and all(not str(v).startswith("ERROR") for v in report.get("tools", {}).values()))


def doctor_text(report):
    """The doctor report as short lines, each with the next step when something is wrong."""
    lines = []

    def line(ok, label, detail=""):
        lines.append("{} {:<12} {}".format("ok  " if ok else "--  ", label, detail).rstrip())

    line(report.get("platform") == "ok", "platform", "" if report.get("platform") == "ok" else report.get("platform") or "")
    for tool, state in report.get("tools", {}).items():
        line(not str(state).startswith("ERROR"), Path(tool).name, str(state).replace("ERROR: ", ""))
    runtime = report.get("runtime")
    line(runtime == "ok", "runtime", "" if runtime == "ok" else "not set up (run: pybox setup)")
    vm = report.get("vm")
    line(vm == "Running", "vm", (vm or "absent") + ("" if vm == "Running" else " (start it with: pybox vm start)"))
    guard = report.get("guard")
    line(guard == "ok", "engine", "" if guard == "ok" else str(guard))
    for name, state in (report.get("images") or {}).items():
        line(state == "ok", "image " + name, "" if state == "ok" else str(state))
    pending = report.get("pending_attempts")
    if pending:
        line(False, "leftovers", "{} unresolved attempt(s); see: pybox cleanup".format(len(pending)))
    return lines
