"""Box profiles and bounded file transfer for the restricted engine.

The default box is exactly the qualified M3–M5 box. Everything else is opt-in per run:
a second image with pinned packages, a longer deadline, and files copied in and out
over the same attach streams. No host folder is ever shared with the VM or the box.
"""
import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

MIB = 1024 * 1024
DEFAULT_TIMEOUT_S = 2.0
MAX_TIMEOUT_S = 30.0
TMPFS = "rw,nosuid,nodev,noexec,size=16m,mode=1777"
TMPFS_FILES = "rw,nosuid,nodev,noexec,size=64m,mode=1777"
MAX_FILES = 64
MAX_FILE_BYTES = 8 * MIB  # in total, each direction
MAX_NAME_BYTES = 512
_PART = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}")
# Base64 plus a bounded manifest line; the host never captures more than this extra.
OUTPUT_WIRE_CAP = (MAX_FILE_BYTES + 2) // 3 * 4 + 65536
MARKER = "\x1ePYBOX-OUTPUTS "

# Memory, CPU and task limits per image. stdlib is the qualified baseline.
PROFILES = {
    "stdlib": dict(memory=128 * MIB, nano_cpus=500_000_000, pids=32),
    "data": dict(memory=512 * MIB, nano_cpus=1_000_000_000, pids=64),
}
DATA_RECIPE = Path(__file__).with_name("images") / "data.lock"
# Your own images: a name, and a lock file of exact pins with hashes. They get the data limits.
IMAGE_NAME = re.compile(r"[a-z][a-z0-9-]{1,30}")
BUILT_IN = ("stdlib", "data")
MAX_LOCK_BYTES = 65536
MAX_LOCK_PACKAGES = 200
_PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9._+!-]*)((?: --hash=sha256:[0-9a-f]{64})+)")
# Applied when the data image is committed; part of the recipe fingerprint.
# matplotlib keeps its font cache in the box's scratch space, because the rest is read-only.
DATA_CHANGES = ("ENV OPENBLAS_NUM_THREADS=1", "ENV OMP_NUM_THREADS=1", "ENV MPLBACKEND=Agg", "ENV MPLCONFIGDIR=/tmp/matplotlib")

# PID 1's child for opt-in runs (another image, files, or a longer deadline): unpack inputs,
# run the program as `python -` would, append any outputs after a per-run boundary, then
# keep the box open for `linger` seconds so the trusted watcher gets a reading after the
# program's work. It runs as the untrusted program's own user, so everything it sends back
# is treated as untrusted program data, and a program can cut the linger short.
BOOTSTRAP = r'''import base64,builtins,json,os,stat,sys,time,traceback
t0=time.monotonic()
r=sys.stdin.buffer
h=r.readline(65536)
if not h.startswith(b"PYBOX1 "):sys.exit(125)
h=json.loads(h[7:])
code=r.read(h["code"])
os.mkdir("/tmp/input",0o755)
for n,s in h["files"]:
 p="/tmp/input/"+n
 os.makedirs(os.path.dirname(p),0o755,exist_ok=True)
 with open(p,"wb") as f:f.write(r.read(s))
 os.chmod(p,0o444)
if h["outputs"]:os.mkdir("/tmp/output",0o755)
sys.stdin=open(os.devnull)
os.chdir("/tmp")
sys.argv=["-"]
st=0
m=type(sys)("__main__");m.__builtins__=builtins;sys.modules["__main__"]=m
try:exec(compile(code,"<stdin>","exec"),m.__dict__)
except SystemExit as e:
 c=e.code
 if c is None:st=0
 elif isinstance(c,int):st=c
 else:print(c,file=sys.stderr);st=1
except BaseException as e:
 traceback.print_exception(type(e),e,e.__traceback__.tb_next);st=1
if h["outputs"]:
 try:sys.stdout.flush();sys.stderr.flush()
 except BaseException:pass
 fs=[];sk=[];blob=bytearray()
 for d,ds,ns in os.walk("/tmp/output"):
  for x in [x for x in ds if os.path.islink(os.path.join(d,x))]:sk.append(os.path.relpath(os.path.join(d,x),"/tmp/output")[:512]);ds.remove(x)
  ds.sort()
  for n in sorted(ns):
   p=os.path.join(d,n);rel=os.path.relpath(p,"/tmp/output")
   try:
    m=os.lstat(p)
    if not stat.S_ISREG(m.st_mode) or len(fs)>=64 or len(blob)+m.st_size>8388608:raise ValueError
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,"rb") as f:b=f.read(8388608-len(blob)+1)
    if len(blob)+len(b)>8388608:raise ValueError
    fs.append([rel,len(b)]);blob+=b
   except Exception:sk.append(rel[:512])
 out=("\x1ePYBOX-OUTPUTS "+h["boundary"]+" "+json.dumps({"files":fs,"skipped":sk[:64]})+"\n").encode()+base64.b64encode(bytes(blob))+b"\n"
 v=memoryview(out)
 while v:v=v[os.write(1,v):]
try:sys.stdout.flush();sys.stderr.flush()
except BaseException:pass
time.sleep(max(0.0,min(h["linger"],h["deadline"]-(time.monotonic()-t0)-0.25)))
sys.exit(st)
'''


@dataclass(frozen=True)
class Box:
    """Everything that differs between boxes; the policy check compares each field."""
    image: str
    ref: str
    memory: int
    nano_cpus: int
    pids: int
    files: bool = False  # PID 1 runs the bootstrap
    recipe: str = None
    moves_files: bool = False  # scratch space grows for copies in and out

    @property
    def tmpfs(self):
        return TMPFS_FILES if self.moves_files else TMPFS

    @property
    def tmpfs_bytes(self):
        return 64 * MIB if self.moves_files else 16 * MIB

    @property
    def cpus(self):
        return format(self.nano_cpus / 1e9, "g")


def check_image_name(name):
    if not isinstance(name, str) or not IMAGE_NAME.fullmatch(name):
        raise ValueError("image names are 2–31 lowercase letters, digits or '-', starting with a letter")
    return name


def make_box(image, ref, files=False, recipe=None, moves_files=None):
    if image != "stdlib":
        check_image_name(image)
    moves_files = files if moves_files is None else moves_files
    return Box(image=image, ref=ref, files=bool(files), recipe=recipe, moves_files=bool(files and moves_files),
               **PROFILES.get(image, PROFILES["data"]))


def recipe_text():
    """The data image recipe: base, exact wheels with hashes, and committed settings."""
    return DATA_RECIPE.read_text()


def check_lock(text):
    """Accept only exact pins with SHA-256 hashes; return the normalized lock.

    Comments and line continuations (as written by `uv pip compile --generate-hashes`)
    are allowed. Options, URLs, editable installs, local paths and unpinned names are
    not, so pip can only install the exact wheels named here.
    """
    if not isinstance(text, str) or len(text.encode()) > MAX_LOCK_BYTES:
        raise ValueError("lock file must be text of at most 64 KiB")
    joined = re.sub(r"\\\s*\n", " ", text)
    pins, names = [], set()
    for number, raw in enumerate(joined.splitlines(), 1):
        line = re.sub(r"\s+", " ", raw.split("#", 1)[0]).strip()
        if not line:
            continue
        match = _PIN.fullmatch(line)
        if not match:
            raise ValueError("lock line {} is not an exact pin with --hash=sha256:… : {!r}".format(number, raw.strip()[:80]))
        key = match.group(1).lower().replace("_", "-").replace(".", "-")
        if key in names:
            raise ValueError("package listed twice: " + match.group(1))
        names.add(key)
        pins.append(line)
    if not pins:
        raise ValueError("lock file has no packages")
    if len(pins) > MAX_LOCK_PACKAGES:
        raise ValueError("at most {} packages".format(MAX_LOCK_PACKAGES))
    return "\n".join(pins) + "\n"


def recipe_sha256(base_ref, lock=None):
    material = json.dumps(dict(base=base_ref, lock=recipe_text() if lock is None else lock, changes=list(DATA_CHANGES)), sort_keys=True)
    return hashlib.sha256(material.encode()).hexdigest()


def recipe_packages(lock=None):
    return dict(re.findall(r"(?m)^([A-Za-z0-9_.-]+)==([^\s\\]+)", recipe_text() if lock is None else lock))


def check_name(name):
    """A relative path of up to 4 plain parts: no dot files, '..', links or odd characters."""
    if not isinstance(name, str) or len(name.encode()) > MAX_NAME_BYTES:
        raise ValueError("file name too long or not text")
    parts = name.split("/")
    if not 1 <= len(parts) <= 4 or any(not _PART.fullmatch(p) for p in parts):
        raise ValueError("unsupported file name: {!r} (use letters, digits, '.', '_', '-'; up to 4 folders deep)".format(name[:80]))
    return name


def check_files(files, what="input"):
    """Validate (name, bytes) pairs against the per-direction bounds."""
    files = list(files)
    if len(files) > MAX_FILES:
        raise ValueError("at most {} {} files".format(MAX_FILES, what))
    names, total = set(), 0
    for name, data in files:
        check_name(name)
        if not isinstance(data, (bytes, bytearray)):
            raise ValueError("{} file content must be bytes".format(what))
        # macOS folders are usually case-insensitive, so A.txt and a.txt would collide there.
        key = name.casefold()
        if key in names or any(n.startswith(key + "/") or key.startswith(n + "/") for n in names):
            raise ValueError("duplicate or overlapping {} name (names that differ only in case count as the same): {}".format(what, name))
        names.add(key)
        total += len(data)
    if total > MAX_FILE_BYTES:
        raise ValueError("{} files exceed {} MiB in total".format(what, MAX_FILE_BYTES // MIB))
    return [(n, bytes(d)) for n, d in files]


def linger_for(timeout_s):
    """How long the box stays open after the program: one watcher sampling gap, plus margin."""
    return 0.12 if timeout_s <= 2 else round(round(max(0.05, float(timeout_s) / 44), 2) + 0.07, 2)


def opt_in(image, files, timeout_s):
    """Runs that use the bootstrap: anything beyond the qualified default box."""
    return image != "stdlib" or bool(files) or timeout_s > DEFAULT_TIMEOUT_S


def frame(source, inputs, outputs, boundary, linger=0.0, deadline=DEFAULT_TIMEOUT_S):
    """Standard input for the bootstrap: one header line, the program, then each file.

    The linger is cut short so it never runs into the deadline: a program that finishes
    just in time keeps its own exit status.
    """
    header = dict(code=len(source), files=[[n, len(d)] for n, d in inputs], outputs=bool(outputs), boundary=boundary,
                  linger=float(linger), deadline=float(deadline))
    return b"PYBOX1 " + json.dumps(header, separators=(",", ":")).encode() + b"\n" + source + b"".join(d for _, d in inputs)


def describe(files):
    return [dict(name=n, bytes=len(d), sha256=hashlib.sha256(d).hexdigest()) for n, d in files]


def safe_names(names, limit=MAX_FILES, budget=4096):
    """Names the program chose, made safe to print and to encode: printable ASCII only
    (anything else becomes \\xNN), at most 128 characters each, 4 KiB in total."""
    out, used = [], 0
    for raw in names if isinstance(names, list) else []:
        if not isinstance(raw, str) or len(out) >= limit:
            continue
        text = "".join(c if " " <= c <= "~" else "\\x{:02x}".format(ord(c) & 0xFF) for c in raw[:128])
        if used + len(text) > budget:
            out.append("…")
            break
        out.append(text)
        used += len(text)
    return out


def split_outputs(stdout, boundary):
    """Separate program output from the appended transfer. Returns (stdout, files, skipped, error).

    Everything here was produced inside the box, so it is parsed strictly and bounded;
    any doubt gives no files and a stated reason, never a partial guess.
    """
    marker = MARKER + boundary + " "
    at = stdout.rfind(marker)
    if at < 0:
        return stdout, [], [], "no transfer received (the program may not have finished)"
    program, rest = stdout[:at], stdout[at + len(marker):]
    try:
        line, payload = rest.split("\n", 1)
        manifest = json.loads(line)
        if set(manifest) != {"files", "skipped"} or not isinstance(manifest["files"], list) or not isinstance(manifest["skipped"], list):
            raise ValueError("manifest shape")
        if payload.endswith("\n"):
            payload = payload[:-1]
        if "\n" in payload or len(payload) > OUTPUT_WIRE_CAP:
            raise ValueError("payload shape")
        blob = base64.b64decode(payload.encode("ascii"), validate=True)
        files, offset = [], 0
        for entry in manifest["files"]:
            name, size = entry
            if type(size) is not int or size < 0:
                raise ValueError("size")
            files.append((name, blob[offset:offset + size]))
            offset += size
        if offset != len(blob):
            raise ValueError("sizes do not add up")
        files = check_files(files, "output")
        return program, files, safe_names(manifest["skipped"]), None
    except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
        return program, [], [], "transfer rejected: " + str(exc)[:200]
