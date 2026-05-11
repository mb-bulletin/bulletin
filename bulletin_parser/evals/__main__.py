"""Eval CLI."""
from __future__ import annotations
import argparse
import sys

from .cases import all_cases
from .diff import diff_runs
from .report import render_diff, render_run
from .runner import load_run, run_evals, save_run


def cmd_list_cases(args):
    cases = all_cases()
    print(f"{len(cases)} case(s):")
    for c in cases:
        print(f"  [{c.flavor}] {c.id}: {c.description}")
    return 0


def cmd_run(args):
    run = run_evals(model=args.model)
    if args.output:
        save_run(run, args.output)
        print(f"Wrote {args.output}", file=sys.stderr)
    print(render_run(run))
    return 0


def cmd_show(args):
    print(render_run(load_run(args.path)))
    return 0


def cmd_compare(args):
    before = load_run(args.before)
    after = load_run(args.after)
    diff = diff_runs(before, after)
    print(render_diff(diff))
    return 1 if diff.regressions else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("list-cases"); s.set_defaults(func=cmd_list_cases)
    s = sub.add_parser("run")
    s.add_argument("--model", default="claude-opus-4-5")
    s.add_argument("-o", "--output")
    s.set_defaults(func=cmd_run)
    s = sub.add_parser("show"); s.add_argument("path"); s.set_defaults(func=cmd_show)
    s = sub.add_parser("compare")
    s.add_argument("before"); s.add_argument("after")
    s.set_defaults(func=cmd_compare)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
