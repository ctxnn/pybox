"""Disposable real CLI/engine supervisor under a validation owner's outer lock."""
import argparse
from contextlib import nullcontext
from dataclasses import asdict
import json
from pathlib import Path
import sys

MAIN=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MAIN))
from pybox import container
from pybox import __main__ as cli


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner-file',type=Path,required=True)
    parser.add_argument('--result',type=Path,required=True)
    parser.add_argument('--armed',type=Path,required=True)
    parser.add_argument('--policy-rejection',action='store_true')
    parser.add_argument('--timeout',type=float,default=2)
    args=parser.parse_args()
    assert args.owner_file.parent==container.ROOT/'tmp' and args.owner_file.name.startswith('m4-validation-owner-')
    container.OWNER_FILE=args.owner_file
    container._admission=nullcontext  # Parent holds the same actual installation lock.
    original_start=container._Observer.start
    def armed(observer):
        original_start(observer)
        args.armed.write_text(json.dumps(dict(identity=observer.control.identity,container_id=observer.control.cid))+'\n')
    container._Observer.start=armed
    if args.policy_rejection:
        original_create=container._create_args
        def stricter_wrong_policy(identity,timeout_s):
            flags=original_create(identity,timeout_s)
            flags[flags.index('--memory=128m')]='--memory=120m'
            flags[flags.index('--memory-swap=128m')]='--memory-swap=120m'
            return flags
        container._create_args=stricter_wrong_policy
    original_run=container.run_container
    def audited(source,**kwargs):
        result=original_run(source,**kwargs)
        args.result.write_text(json.dumps(asdict(result),indent=2)+'\n')
        return result
    cli.run_container=audited
    return cli.main(['container','--inspect','--timeout',str(args.timeout)])


if __name__=='__main__': sys.exit(main())
