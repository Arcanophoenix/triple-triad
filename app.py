#!/usr/bin/env python3
"""Packaged-app entry point.

    TripleTriad              # start the web GUI, open a browser  (the usual way)
    TripleTriad gui 9000     # ... on a specific port
    TripleTriad recommend "Yellow Moon"      # any ./tt-cli sub-command still works
    TripleTriad review

Running from a source checkout?  Use ./tt-cli instead - it's the same commands.
This file exists so PyInstaller has a single, import-clean thing to bundle.
"""
import multiprocessing
import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE / "scripts"):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

import tt.paths as _paths  # noqa: E402  (also pins the package for PyInstaller)

_COMMANDS = {
    "gui": "gui",
    "play": "play",
    "solve": "solve",
    "recommend": "recommend",
    "difficulty": "difficulty",
    "review": "review",
    "scrape": "scrape_npc",
    "deck": "deck",
    "data": "extract_wiki",
}


def _seed_user_data() -> None:
    """First frozen launch: give the user a real collection.json to edit."""
    if not _paths.FROZEN:
        return
    dst = _paths.user_path("collection.json")
    src = _paths.BUNDLED_DATA / "collection.example.json"
    if not dst.exists() and src.is_file():
        _paths.ensure_user_dir()
        shutil.copyfile(src, dst)


def main() -> int:
    argv = sys.argv[1:]
    has_cmd = bool(argv) and argv[0] in _COMMANDS
    cmd = argv[0] if has_cmd else "gui"
    rest = argv[1:] if has_cmd else argv

    _seed_user_data()

    mod = __import__(_COMMANDS[cmd])
    entry = getattr(mod, "main", None)
    if entry is None:
        print(f"{cmd}: no entry point", file=sys.stderr)
        return 2
    sys.argv = [cmd, *rest]
    return int(entry() or 0)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
