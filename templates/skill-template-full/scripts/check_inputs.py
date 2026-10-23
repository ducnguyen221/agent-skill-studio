#!/usr/bin/env python3
"""Check one required local input for existence, without modifying it.

Usage: python3 scripts/check_inputs.py path/to/input.file
Requires: Python 3.9+ (standard library only).
"""
import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Verify that an input file exists and is readable")
    parser.add_argument("path", help="path to the required input file")
    args = parser.parse_args()
    p = Path(args.path).expanduser()
    if not p.is_file():
        print("ERROR: input file is missing or is not a regular file: %s" % p, file=sys.stderr)
        print("Fix: provide a readable file path; no files were modified.", file=sys.stderr)
        return 1
    try:
        with p.open("rb") as fp:
            fp.read(1)
    except OSError as exc:
        print("ERROR: cannot read input %s: %s" % (p, exc), file=sys.stderr)
        return 1
    print("PASS: %s (size=%d bytes)" % (p, p.stat().st_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
