#!/usr/bin/env python3
"""
Pre-commit hook: block commits containing personal/sensitive data.

Banned strings are loaded from a local file '.banned-strings' (one pattern per line).
This file is gitignored and must be created manually on each developer machine.
See '.banned-strings.example' for the expected format.
"""
import sys
from pathlib import Path

BANNED_FILE = Path(__file__).parent.parent / ".banned-strings"


def load_banned():
    if not BANNED_FILE.exists():
        print(
            f"[no-sensitive-strings] WARNING: {BANNED_FILE} not found. "
            "Hook is inactive. Create it from .banned-strings.example."
        )
        return []
    lines = BANNED_FILE.read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.startswith("#")]


def main(files):
    banned = load_banned()
    if not banned:
        return 0
    found = False
    for filepath in files:
        try:
            content = open(filepath, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for pattern in banned:
            if pattern in content:
                print(f"[no-sensitive-strings] Found banned string in: {filepath}")
                found = True
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
