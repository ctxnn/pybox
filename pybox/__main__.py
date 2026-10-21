import argparse
from dataclasses import asdict
import json
import sys

from .runner import RunnerError, run_file
from .container import MAX_SOURCE_BYTES, cleanup_containers, run_container
from . import boxes


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="pybox",
        description="Run Python you don't trust in a fresh, sealed box on your Mac, and get a receipt. "
                    "Start with: pybox setup, pybox vm start, pybox exec script.py",
        epilog="`pybox run --unsafe-local` runs on your Mac with NO isolation; it is a learning tool, not a sandbox."
    )
    from . import __version__
    parser.add_argument("--version", action="version", version="pybox " + __version__)
    commands = parser.add_subparsers(dest="command", required=True)
    sealed = commands.add_parser("exec", help="run a Python file (or - for standard input) in a fresh sealed box")
    sealed.add_argument("path", help="the program, or - to read it from standard input")
    sealed.add_argument("--image", default="stdlib", metavar="NAME",
                        help="stdlib (default), data (numpy, pandas, matplotlib; install with: pybox setup --yes --with data), "
                             "or one you built with: pybox image build")
    sealed.add_argument("--timeout", type=float, default=boxes.DEFAULT_TIMEOUT_S, metavar="SECONDS",
                        help="deadline, 2 by default, up to {:g}".format(boxes.MAX_TIMEOUT_S))
    sealed.add_argument("--input", action="append", default=[], metavar="PATH",
                        help="copy a file or folder in, at /tmp/input/ (repeatable; 64 files, 8 MiB in total)")
    sealed.add_argument("--output", metavar="DIR",
                        help="bring back what the program writes to /tmp/output/ into this new or empty folder")
    sealed.add_argument("--max-output-bytes", type=int, default=65536, metavar="BYTES_PER_STREAM")
    sealed.add_argument("--json", action="store_true", help="print the full versioned record instead of the program's output and a receipt")
    sealed.add_argument("-q", "--quiet", action="store_true", help="print the program's output only, no receipt")
    mcp = commands.add_parser("mcp", help="serve the run_python tool to an AI agent over local stdio (MCP)")
    mcp.add_argument("--max-timeout", type=float, default=boxes.DEFAULT_TIMEOUT_S, metavar="SECONDS",
                     help="longest run an agent may ask for (default 2, up to {:g})".format(boxes.MAX_TIMEOUT_S))
    mcp.add_argument("--images", default="stdlib", metavar="LIST",
                     help="comma-separated images agents may use: stdlib (default), data, or your own")
    restricted = commands.add_parser("container", help="dedicated-container execution; source from stdin")
    restricted.add_argument("--inspect", action="store_true", help="emit the versioned inspection record")
    restricted.add_argument("--timeout", type=float, default=2.0, metavar="SECONDS")
    restricted.add_argument("--max-output-bytes", type=int, default=65536, metavar="BYTES_PER_STREAM")
    cleanup = commands.add_parser("cleanup", help="report owned containers and remove verified expired stopped leftovers")
    cleanup.add_argument(
        "--resolve-attempt", action="append", default=[], metavar="RUN",
        help="retire an unacknowledged CREATE attempt (32-hex run token) once past expiry plus margin, "
             "if a complete identity query is empty",
    )
    setup = commands.add_parser("setup", help="create the dedicated restricted runtime (dry run unless --yes)")
    setup.add_argument("--yes", action="store_true", help="carry out the printed plan")
    setup.add_argument("--with", dest="with_images", action="append", default=[], metavar="IMAGE",
                       help="also build an optional image: data (numpy, pandas, matplotlib)")
    vm = commands.add_parser("vm", help="start, stop or show the dedicated VM profile")
    vm.add_argument("action", choices=["start", "stop", "status"])
    image = commands.add_parser("image", help="build, list or remove images with extra packages")
    image_commands = image.add_subparsers(dest="image_command", required=True)
    build = image_commands.add_parser("build", help="build an image from a lock file of exact pins with hashes (VM must be running)")
    build.add_argument("name", help="2–31 lowercase letters, digits or '-'")
    build.add_argument("--lock", required=True, metavar="FILE",
                       help="requirements with --hash=sha256 for every package, e.g. from: uv pip compile --generate-hashes")
    image_commands.add_parser("list", help="list images and whether they match their recipe")
    remove = image_commands.add_parser("rm", help="remove an image you built (VM must be running)")
    remove.add_argument("name")
    doctor = commands.add_parser("doctor", help="read-only check of platform, tools, runtime, VM and images")
    doctor.add_argument("--json", action="store_true", help="machine-readable report")
    run = commands.add_parser("run", help="execute one local Python file")
    run.add_argument("path")
    run.add_argument("--unsafe-local", action="store_true", help="acknowledge host execution")
    run.add_argument("--timeout", type=float, default=2.0, metavar="SECONDS")
    run.add_argument("--max-output-bytes", type=int, default=65536, metavar="BYTES_PER_STREAM")
    run.add_argument(
        "--cpu-soft-limit", type=int, metavar="CPU_SECONDS",
        help="experimental per-process CPU soft threshold (1–60); NOT a non-bypassable CPU cap",
    )
    args = parser.parse_args(argv)
    if args.command == "mcp":
        from .mcp import serve
        images = tuple(dict.fromkeys(i.strip() for i in args.images.split(",") if i.strip()))
        try:
            if not images:
                raise ValueError("--images needs at least one image")
            for name in images:
                if name != "stdlib":
                    boxes.check_image_name(name)
        except ValueError as exc:
            parser.error(str(exc))
        if not 0 < args.max_timeout <= boxes.MAX_TIMEOUT_S:
            parser.error("--max-timeout must be greater than 0 and at most {:g}".format(boxes.MAX_TIMEOUT_S))
        return serve(max_timeout=args.max_timeout, images=images)
    if args.command == "exec":
        return _exec(parser, args)
    if args.command == "image":
        return _image(parser, args)
    if args.command in ("setup", "vm", "doctor"):
        from . import runtime_setup
        try:
            if args.command == "setup":
                return runtime_setup.setup(args.yes, with_images=args.with_images)
            if args.command == "vm":
                return runtime_setup.vm(args.action)
            report = runtime_setup.doctor()
            if args.json:
                print(json.dumps(report, indent=2))
            else:
                print("\n".join(runtime_setup.doctor_text(report)))
            return 0 if runtime_setup.doctor_ok(report) else 1
        except RuntimeError as exc:
            print("pybox: " + str(exc), file=sys.stderr)
            return 125
    if args.command == "cleanup":
        result = cleanup_containers(args.resolve_attempt)
        print(json.dumps(asdict(result), indent=2))
        return 0 if result.complete and not result.runner_error else 125
    try:
        if args.command == "container":
            source = sys.stdin.buffer.read(MAX_SOURCE_BYTES + 1)
            if len(source) > MAX_SOURCE_BYTES:
                raise ValueError("source exceeds 65536 bytes")
            result = run_container(source.decode("utf-8"),timeout_s=args.timeout,max_output_bytes=args.max_output_bytes)
        else:
            result = run_file(
                args.path,
                unsafe_local=args.unsafe_local,
                timeout_s=args.timeout,
                max_output_bytes=args.max_output_bytes,
                cpu_soft_limit_s=args.cpu_soft_limit,
            )
    except (PermissionError, ValueError) as exc:
        parser.error(str(exc))
    except RunnerError as exc:
        print("pybox: runner error: {}".format(exc), file=sys.stderr)
        return 125
    print(json.dumps(result.record if args.command=="container" and args.inspect else asdict(result), indent=2))
    if getattr(result,"cancelled",False):
        return 130
    if result.runner_error:
        return 125
    if result.timed_out:
        return 124
    return 0 if result.returncode == 0 else 1


def _image(parser, args):
    from . import container, runtime_setup
    try:
        if args.image_command == "build":
            if args.name in boxes.BUILT_IN:
                raise ValueError("'{}' is built in; choose another name (data is built with: pybox setup --yes --with data)".format(args.name))
            with open(args.lock, encoding="utf-8") as file:
                lock = boxes.check_lock(file.read(boxes.MAX_LOCK_BYTES + 1))
            container._guard()
            runtime_setup.build_image(args.name, lock=lock)
        elif args.image_command == "list":
            for name, state, entry in runtime_setup.list_images():
                packages = ", ".join("{}=={}".format(k, v) for k, v in entry.get("packages", {}).items())
                print("{:<12} {:<28} {}".format(name, state[:28], (packages[:90] + "…") if len(packages) > 90 else packages))
        else:
            if args.name in ("stdlib",):
                raise ValueError("stdlib is built in and can't be removed")
            runtime_setup.remove_image(args.name)
        return 0
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    except RuntimeError as exc:
        print("pybox: " + str(exc), file=sys.stderr)
        return 125


def _status(result):
    if result.cancelled:
        return 130
    if result.runner_error:
        return 125
    if result.timed_out:
        return 124
    return 0 if result.returncode == 0 else 1


def _exec(parser, args):
    """pybox exec: the sealed box with a readable receipt (or the full record with --json)."""
    from . import receipt, transfer
    try:
        if args.path == "-":
            source = sys.stdin.buffer.read(MAX_SOURCE_BYTES + 1)
        else:
            with open(args.path, "rb") as file:
                source = file.read(MAX_SOURCE_BYTES + 1)
        if len(source) > MAX_SOURCE_BYTES:
            raise ValueError("program exceeds 65536 bytes")
        inputs = transfer.collect_inputs(args.input)
        output_dir = transfer.prepare_output_dir(args.output) if args.output else None
        result = run_container(source.decode("utf-8"), timeout_s=args.timeout, max_output_bytes=args.max_output_bytes,
                               image=args.image, inputs=inputs, collect_outputs=output_dir is not None)
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))
    written = None
    if output_dir is not None:
        try:
            if result.output_files:
                transfer.write_outputs(output_dir, result.output_files)
                written = str(output_dir.path)
        except (OSError, ValueError) as exc:
            print("pybox: could not write outputs (nothing was written): {}".format(exc), file=sys.stderr)
        finally:
            output_dir.close()
    if args.json:
        print(json.dumps(result.record, indent=2))
        return _status(result)
    sys.stdout.write(result.stdout)
    sys.stdout.flush()
    sys.stderr.write(result.stderr)
    if not args.quiet:
        lines = receipt.render(result.record, output_dir=written)
        # Program output came first; reset colours and the scroll region so it can't disguise the receipt.
        reset = "\x1b[0m\x1b[r" if sys.stderr.isatty() else ""
        print(reset + ("\n" if result.stdout or result.stderr else "") + "\n".join(lines), file=sys.stderr)
    return _status(result)


if __name__ == "__main__":
    sys.exit(main())
