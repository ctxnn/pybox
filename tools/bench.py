"""Time where a sealed run spends its time, phase by phase, over N real runs.

    python tools/bench.py [--runs 10] [--image stdlib|data] [--json]

Needs the VM running (pybox vm start). Each run is a full fresh box: admission and
reconciliation, create, settings readback, watcher arm, the program, removal.
Times come from PyBox's own recorded operations; the program itself is `pass`.
"""
import argparse
import datetime
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pybox.container import run_container  # noqa: E402


def _utc(value):
    return datetime.datetime.fromisoformat(value)


def phases(result):
    ops = [o for o in result.operations if o.get("executed")]
    recon = sum(o.get("elapsed_s", 0) for o in (result.reconciliation or {}).get("operations", []))
    start = next(o for o in ops if o["phase"] == "start")
    create = next(o for o in ops if o["phase"] == "create")
    readback = next(o for o in ops if o["phase"] == "inspect")
    after = ops[ops.index(start) + 1:]
    return dict(
        reconcile=recon,
        create=create["elapsed_s"],
        readback=readback["elapsed_s"],
        watcher_arm=max(0.0, (_utc(start["start_utc"]) - _utc(readback["end_utc"])).total_seconds()),
        run=start["elapsed_s"],
        teardown=sum(o.get("elapsed_s", 0) for o in after if o["phase"] != "observe"),
        total=result.lifecycle_elapsed_s,
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--image", default="stdlib")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    samples = []
    for i in range(args.runs):
        began = time.monotonic()
        result = run_container("pass", image=args.image)
        if result.runner_error or result.returncode != 0 or not result.removed:
            print("run {} failed: {}".format(i, result.runner_error), file=sys.stderr)
            return 1
        sample = phases(result)
        sample["caller_wall"] = time.monotonic() - began
        samples.append(sample)
    keys = list(samples[0])
    summary = {k: dict(median=statistics.median(s[k] for s in samples), min=min(s[k] for s in samples),
                       max=max(s[k] for s in samples)) for k in keys}
    if args.json:
        print(json.dumps(dict(runs=args.runs, image=args.image, summary=summary, samples=samples), indent=2))
    else:
        print("{} runs, image {}\n".format(args.runs, args.image))
        print("| Phase | Median (s) | Min | Max |\n| --- | --- | --- | --- |")
        for k in keys:
            print("| {} | {:.3f} | {:.3f} | {:.3f} |".format(k, summary[k]["median"], summary[k]["min"], summary[k]["max"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
