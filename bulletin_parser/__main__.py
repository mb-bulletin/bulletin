"""
CLI: parse a bulletin PDF (or text file) into structured JSON.

Usage:
    python -m bulletin_parser bulletin.pdf
    python -m bulletin_parser bulletin.pdf -o bulletin.json
    python -m bulletin_parser bulletin.txt --model claude-opus-4-5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .extract import load_text
from .parser import DEFAULT_MODEL, parse_bulletin, to_json


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", help="Path to a .pdf or .txt bulletin file.")
    p.add_argument("-o", "--output", help="Where to write JSON. Default: stdout.")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Anthropic model to use.")
    args = p.parse_args(argv)

    text = load_text(args.source)
    bulletin = parse_bulletin(text, model=args.model)
    out = to_json(bulletin)

    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"Wrote {args.output} ({len(out)} bytes)", file=sys.stderr)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
