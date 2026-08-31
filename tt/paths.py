"""Filesystem locations, aware of PyInstaller-frozen vs source-tree runs.

Read-only resources (the card DB, NPC list, static GUI assets, card art) ship
inside the frozen app and live under :data:`RESOURCE_ROOT`.  Anything the app
writes -- your collection, the match history, the review cache, hand-recorded
NPC decks -- lives under :data:`USER_DIR` so it survives an upgrade and isn't
trapped in a read-only bundle.

In a normal source checkout ``RESOURCE_ROOT`` and ``USER_DIR`` are both the repo
root's ``data/``, so behaviour is byte-for-byte what it was before packaging
existed.  Set ``TRIPLE_TRIAD_HOME`` to force the writable dir somewhere else
(tests use this; a frozen app can point it back at a checkout).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", None) or Path(sys.executable).parent)
else:
    RESOURCE_ROOT = Path(__file__).resolve().parent.parent

BUNDLED_DATA = RESOURCE_ROOT / "data"
GUI_DIR = RESOURCE_ROOT / "gui"
REFERENCE_DIR = RESOURCE_ROOT / "reference"


def _user_dir() -> Path:
    override = os.environ.get("TRIPLE_TRIAD_HOME")
    if override:
        return Path(override).expanduser()
    if not FROZEN:
        return RESOURCE_ROOT / "data"
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "TripleTriad"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "TripleTriad"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "triple-triad"


USER_DIR = _user_dir()


def user_path(name: str) -> Path:
    """Path to a writable data file (no directory is created)."""
    return USER_DIR / name


def ensure_user_dir() -> Path:
    USER_DIR.mkdir(parents=True, exist_ok=True)
    return USER_DIR
