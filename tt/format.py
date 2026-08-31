"""Parse and render boards / decks for the CLI.

Board spec: 9 comma-separated tokens for cells 1..9 (row-major).  Each token is
``.`` for empty or ``<card>@A`` / ``<card>@B`` (``<card>`` uses loose name
matching).  Example::

    "Ifrit@A, ., ., ., Garuda@B, ., ., ., ."
"""
from __future__ import annotations

from .data import CARDS, resolve
from .model import EMPTY_BOARD

OWNER_CH = {0: "A", 1: "B"}
CH_OWNER = {"A": 0, "a": 0, "B": 1, "b": 1}


def parse_board(spec: str) -> tuple:
    toks = [t.strip() for t in spec.split(",")]
    if len(toks) != 9:
        raise ValueError(f"board needs 9 cells, got {len(toks)}")
    board = list(EMPTY_BOARD)
    for i, t in enumerate(toks):
        if t in (".", "", "-"):
            continue
        if "@" not in t:
            raise ValueError(f"cell {i + 1}: expected '<card>@A' or '.', got {t!r}")
        name, _, own = t.rpartition("@")
        if own not in CH_OWNER:
            raise ValueError(f"cell {i + 1}: owner must be A or B, got {own!r}")
        board[i] = (resolve(name).id, CH_OWNER[own])
    return tuple(board)


def parse_deck(spec) -> list:
    names = spec if isinstance(spec, list) else [s for s in spec.split(",")]
    return [resolve(s.strip()).id for s in names if s.strip()]


def _cellstr(slot) -> str:
    if slot is None:
        return "  .  "
    c = CARDS[slot[0]]
    return f"{OWNER_CH[slot[1]]}:{c.name[:3]}"


def render_board(board) -> str:
    rows = []
    for r in range(3):
        rows.append(" | ".join(f"{_cellstr(board[r * 3 + q]):^12}" for q in range(3)))
    sep = "\n" + "-" * 44 + "\n"
    return sep.join(rows)


def render_hand(hand, label: str) -> str:
    if not hand:
        return f"{label}: (empty)"
    parts = [f"{CARDS[c].name} [{CARDS[c].high}]" for c in hand]
    return f"{label}: " + ", ".join(parts)
