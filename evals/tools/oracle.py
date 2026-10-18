#!/usr/bin/env python3
"""Grade an output text against an oracle file `evals/<skill>/expected/<case-id>.json`.

  oracle.py grade <oracle.json> <output.txt>     # exit 0 = oracle satisfied, 1 = not

Matching rule (fixed here so no grader has to guess): every entry is a regular expression searched with
re.IGNORECASE | re.DOTALL (so `.` crosses newlines; entries bound it with `.{0,N}`).
`must_contain`: every entry must match. `must_not_contain`: no entry may match.
Python 3.9+, standard library only. Read-only.
"""
import json
import re
import sys
from pathlib import Path

FLAGS = re.IGNORECASE | re.DOTALL


def grade(text, oracle):
    missing = [e for e in oracle.get("must_contain", []) if not re.search(e, text, FLAGS)]
    forbidden = [e for e in oracle.get("must_not_contain", []) if re.search(e, text, FLAGS)]
    return {"pass": not missing and not forbidden, "missing": missing, "forbidden_matched": forbidden}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 3 or argv[0] != "grade":
        print(__doc__)
        return 2
    oracle = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    result = grade(Path(argv[2]).read_text(encoding="utf-8"), oracle)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
