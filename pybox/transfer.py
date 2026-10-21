"""Host side of file transfer: read inputs without following links, write outputs without
overwriting anything. Names and sizes are checked again by `boxes.check_files`.
"""
import os
from pathlib import Path
import shutil
import stat
import time
import uuid

from . import boxes

_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _read(path, budget):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as file:
        if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
            raise ValueError("not a regular file: {}".format(path))
        data = file.read(budget + 1)
    if len(data) > budget:
        raise ValueError("input files exceed {} MiB in total".format(boxes.MAX_FILE_BYTES // boxes.MIB))
    return data


def collect_inputs(paths):
    """Each file goes to /tmp/input/<name>; a folder to /tmp/input/<folder>/… . Links are refused."""
    files, budget = [], boxes.MAX_FILE_BYTES
    for raw in paths:
        path = Path(raw)
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("symbolic links are not followed: {}".format(raw))
        if stat.S_ISREG(info.st_mode):
            items = [(path.name, path)]
        elif stat.S_ISDIR(info.st_mode):
            items = []
            for directory, folders, names in os.walk(path, followlinks=False):
                folders.sort()
                for name in sorted(names) + [f for f in folders if (Path(directory) / f).is_symlink()]:
                    full = Path(directory) / name
                    if full.is_symlink():
                        raise ValueError("symbolic links are not followed: {}".format(full))
                    items.append(((path.name + "/" + str(full.relative_to(path))), full))
        else:
            raise ValueError("not a file or folder: {}".format(raw))
        for name, full in items:
            boxes.check_name(name)
            if len(files) >= boxes.MAX_FILES:
                raise ValueError("at most {} input files".format(boxes.MAX_FILES))
            data = _read(full, budget)
            budget -= len(data)
            files.append((name, data))
    return boxes.check_files(files, "input")


class OutputTarget:
    """Where outputs will go, pinned before the run: the parent folder is opened once, so a
    folder swapped in later can't redirect the writes."""

    def __init__(self, raw):
        path = Path(raw)
        if not path.name or path.name in (".", ".."):
            raise ValueError("output must name a new or empty folder: {}".format(raw))
        self.path, self.name = path, path.name
        self.parent = os.open(path.parent if str(path.parent) else ".", _DIR)
        try:
            info = os.lstat(self.name, dir_fd=self.parent)
        except FileNotFoundError:
            info = None
        if info is not None:
            if not stat.S_ISDIR(info.st_mode):
                self.close()
                raise ValueError("output must be a new or empty folder: {}".format(raw))
            fd = os.open(self.name, _DIR, dir_fd=self.parent)
            try:
                if os.listdir(fd):
                    raise ValueError("output folder is not empty: {}".format(raw))
            except ValueError:
                self.close()
                raise
            finally:
                os.close(fd)

    def close(self):
        if self.parent is not None:
            os.close(self.parent)
            self.parent = None


def prepare_output_dir(raw):
    """Check the output folder before the run starts: it must be new or empty."""
    return OutputTarget(raw)


def _quarantine(fd):
    """Mark a returned file the way macOS marks downloads, so Gatekeeper checks it when opened."""
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        libc.fsetxattr.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
        libc.fsetxattr.restype = ctypes.c_int
        value = "0081;{:08x};PyBox;".format(int(time.time())).encode()
        return libc.fsetxattr(fd, b"com.apple.quarantine", value, len(value), 0, 0) == 0
    except (OSError, AttributeError):
        return False


def write_outputs(target, files):
    """Write (name, bytes) pairs into the output folder, all or nothing.

    Files go into a fresh hidden folder next to it, never following links, and that folder
    is renamed into place only when every file was written. Returns how many files were
    marked with the quarantine attribute.
    """
    files = boxes.check_files(files, "output")
    if not isinstance(target, OutputTarget):
        target = OutputTarget(target)
    staging = ".pybox-output-" + uuid.uuid4().hex
    os.mkdir(staging, 0o755, dir_fd=target.parent)
    marked = 0
    try:
        root = os.open(staging, _DIR, dir_fd=target.parent)
        try:
            for name, data in files:
                *folders, leaf = name.split("/")
                fd = os.dup(root)
                try:
                    for folder in folders:
                        try:
                            os.mkdir(folder, 0o755, dir_fd=fd)
                        except FileExistsError:
                            pass
                        child = os.open(folder, _DIR, dir_fd=fd)
                        os.close(fd)
                        fd = child
                    out = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=fd)
                    with os.fdopen(out, "wb") as file:
                        file.write(data)
                        marked += _quarantine(file.fileno())
                finally:
                    os.close(fd)
        finally:
            os.close(root)
        # Replaces the folder only if it is still empty (or absent); never merges.
        os.rename(staging, target.name, src_dir_fd=target.parent, dst_dir_fd=target.parent)
    except BaseException:
        shutil.rmtree(staging, dir_fd=target.parent, ignore_errors=True)
        raise
    return marked
