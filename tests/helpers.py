"""Shared test helpers for building boards and running the resolver."""
from tt.model import EMPTY_BOARD
from tt.rules import resolve_placement

# side order is (N, E, S, W); handy named builders
def sides(n=1, e=1, s=1, w=1):
    return (n, e, s, w)


def build(cells: dict) -> tuple:
    """cells: {cell_index: (Card, owner)} -> board tuple."""
    b = list(EMPTY_BOARD)
    for idx, (card, owner) in cells.items():
        b[idx] = (card.id, owner)
    return tuple(b)


def place(rules, cells: dict, cell: int, card, owner: int):
    """Build a board, drop `card` at `cell` as `owner`, resolve. -> (board, log)."""
    b = list(build(cells))
    b[cell] = (card.id, owner)
    return resolve_placement(rules, tuple(b), cell)


def owners(board) -> tuple:
    return tuple(None if s is None else s[1] for s in board)
