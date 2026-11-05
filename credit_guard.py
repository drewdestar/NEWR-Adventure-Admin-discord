# -*- coding: utf-8 -*-
"""Startup credit guard (phase 3) — NEWR Adventure by NEWR LABS.

Same marker-only design as the main bot's credit_guard.py: it checks
that a short credit marker line is still present, verbatim, in the
entry point and main shared modules, and that the LICENSE file still
carries the NEWR LABS proprietary notice. It does NOT hash or compare
any other code, so ordinary edits and the user's own updates never
trip it. It deters casual copying only; a determined person with the
source could remove this file and its call site — a known limit.

Marker line (must appear verbatim in every REQUIRED_FILES entry):
    # NEWR Adventure by NEWR LABS — credit marker, do not remove.
"""
import sys
from pathlib import Path

# NEWR Adventure by NEWR LABS — credit marker, do not remove.
CREDIT_MARKER = "# NEWR Adventure by NEWR LABS \u2014 credit marker, do not remove."
REQUIRED_FILES = ("bot.py", "data.py", "db.py", "cogs/admin.py")
LICENSE_MARKERS = ("NEWR LABS", "written permission")


def verify_credit_markers(bot_dir=None):
    """Return a list of problems (empty = all markers present)."""
    base = Path(bot_dir) if bot_dir else Path(__file__).resolve().parent
    problems = []
    for rel in REQUIRED_FILES:
        path = base / rel
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            problems.append(f"missing file: {rel}")
            continue
        if CREDIT_MARKER not in text:
            problems.append(f"credit marker missing or altered in: {rel}")
    lic = base / "LICENSE"
    try:
        lic_text = lic.read_text(encoding="utf-8")
    except OSError:
        problems.append("missing file: LICENSE")
        return problems
    for marker in LICENSE_MARKERS:
        if marker not in lic_text:
            problems.append(f"LICENSE notice missing or altered: {marker!r}")
    return problems


def enforce_credit_markers(bot_dir=None):
    """Exit with a clear error if any credit marker is gone."""
    problems = verify_credit_markers(bot_dir)
    if problems:
        print("ERROR: NEWR Adventure Admin credit check failed — the bot "
              "refuses to run.", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("Restore the 'NEWR Adventure by NEWR LABS' credit markers "
              "and the LICENSE file, then start the bot again.",
              file=sys.stderr)
        sys.exit(1)
    return True
