#!/usr/bin/env python3
"""Shim: the one engine lives in skills/skill-creator-studio/scripts/studio.py (SPR-02, FR1)."""
import runpy
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent / "skills" / "skill-creator-studio" / "scripts" / "studio.py"

if not ENGINE.is_file():
    sys.stderr.write("ERROR: engine not found: %s\n" % ENGINE)
    sys.exit(2)

# SystemExit raised by the engine passes through, so its exit code is the shim's exit code.
runpy.run_path(str(ENGINE), run_name="__main__")
