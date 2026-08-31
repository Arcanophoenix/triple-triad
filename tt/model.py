"""Board geometry, rule set, game state, terminal test and scoring.

Cells are 0..8, row-major::

    0 1 2
    3 4 5
    6 7 8

Side indices are 0=N(up) 1=E(right) 2=S(down) 3=W(left); OPP[d] is the facing
side of the neighbour in direction d.  A slot is ``(card_id, owner)`` or ``None``;
owner 0 is player A (by convention "you"), owner 1 is player B (the NPC).
"""
from __future__ import annotations

from dataclasses import dataclass, fields

OPP = (2, 3, 0, 1)

# cell -> tuple of (direction_from_cell, neighbour_cell) for in-board neighbours
NEIGHBORS: dict[int, tuple[tuple[int, int], ...]] = {}
# cell -> tuple of directions that face the board edge (used by Same Wall)
WALLS: dict[int, tuple[int, ...]] = {}


def _build_geometry() -> None:
    # direction: (row delta, col delta) for N, E, S, W
    step = {0: (-1, 0), 1: (0, 1), 2: (1, 0), 3: (0, -1)}
    for c in range(9):
        r, q = divmod(c, 3)
        nb, wl = [], []
        for d, (dr, dq) in step.items():
            nr, nq = r + dr, q + dq
            if 0 <= nr < 3 and 0 <= nq < 3:
                nb.append((d, nr * 3 + nq))
            else:
                wl.append(d)
        NEIGHBORS[c] = tuple(nb)
        WALLS[c] = tuple(wl)


_build_geometry()

EMPTY_BOARD: tuple = (None,) * 9


@dataclass(frozen=True, slots=True)
class RuleSet:
    reverse: bool = False
    fallen_ace: bool = False
    same: bool = False
    same_wall: bool = False
    plus: bool = False
    ascension: bool = False
    descension: bool = False
    swap: bool = False
    chaos: bool = False
    order: bool = False
    sudden_death: bool = False
    all_open: bool = False
    three_open: bool = False
    roulette: bool = False

    _NAMES = {
        "reverse": "reverse",
        "fallen ace": "fallen_ace",
        "same": "same",
        "same wall": "same_wall",
        "plus": "plus",
        "ascension": "ascension",
        "descension": "descension",
        "swap": "swap",
        "chaos": "chaos",
        "order": "order",
        "sudden death": "sudden_death",
        "all open": "all_open",
        "three open": "three_open",
        "roulette": "roulette",
        "combo": None,  # always active in FFXIV; not a toggle
    }

    @classmethod
    def from_names(cls, names) -> "RuleSet":
        kw, unknown = {}, []
        for n in names:
            key = cls._NAMES.get(n.strip().lower(), "?")
            if key == "?":
                unknown.append(n)
            elif key:
                kw[key] = True
        if unknown:
            raise ValueError(f"unknown rule name(s): {unknown}")
        return cls(**kw)

    def names(self) -> list[str]:
        rev = {v: k.title() for k, v in self._NAMES.items() if v}
        return [rev[f.name] for f in fields(self) if getattr(self, f.name)]


@dataclass(frozen=True, slots=True)
class GameState:
    board: tuple            # 9 * (card_id, owner) | None
    hands: tuple            # (tuple[int,...], tuple[int,...]) remaining card ids
    to_move: int            # 0 = A, 1 = B
    rules: RuleSet

    def key(self):
        return (self.board, self.hands, self.to_move)


def is_terminal(state: GameState) -> bool:
    # board full, or the side to move is out of cards (only reachable from
    # inconsistent input - a real match always ends with the board full)
    return None not in state.board or not state.hands[state.to_move]


def score_a(state: GameState) -> int:
    """Cards under A's control at game end: board cards + A's unplayed hand card.

    Total is always 10 (9 on the board + 1 left in hand).  A wins at >=6, 5-5 draws.
    """
    on_board = sum(1 for s in state.board if s is not None and s[1] == 0)
    return on_board + len(state.hands[0])


def value_a(state: GameState) -> int:
    """Card margin from A's perspective, -10..10 (positive = A ahead)."""
    return 2 * score_a(state) - 10
