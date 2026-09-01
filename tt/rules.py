"""Capture resolution for a single placement.

``resolve_placement(rules, board, cell)`` assumes the moving card is already at
``board[cell]`` and returns ``(new_board, log)``.  Resolution order:

1. Same (with Same Wall) and Plus are evaluated against the placed card.
2. The placed card also makes ordinary higher-number captures.
3. Every card flipped by **Same or Plus** (not by an ordinary capture) then makes
   ordinary captures against its own neighbours, cascading.  This is Combo, which
   is always active in FFXIV.

Ordinary comparison honours Reverse and Fallen Ace; Same and Plus are
value-equality tests and ignore both.
"""
from __future__ import annotations

from collections import deque

from .data import CARDS
from .model import NEIGHBORS, OPP, WALLS, RuleSet

# Ascension / Descension (per the FFXIV wiki): each faction card on the board
# gives every card of that faction +1 / -1, stacking.  So N faction cards on the
# board => +/-N (board cards and cards still in hand alike).  Ascension results of
# "11" or higher are treated as an "A" (capped at 10); Descension results of "0"
# or less are treated as a "1".
#
# While a placement is being resolved the card just placed is NOT yet counted
# toward its faction's total - not for itself, and not for its same-faction
# neighbours either.  Every card of that faction sees the pre-placement count
# during the whole resolution (captures + Combo); the counter only ticks up once
# things settle.  So:
#   * a lone placed Primal captures with printed values (Yellow Moon: a placed
#     Garlean stays 9, ties an established lone ascended Primal at 9 - no capture);
#   * a Society card placed next to an established Society card and the card it
#     attacks BOTH still use "1 Society on the board", so printed 6-vs-6 stays a
#     tie under Descension (Noes: Memeroon does not capture Frixio), then both
#     drop to -2 afterwards.
_ASCENSION_MAX = 10

# Fallen Ace, the 1-vs-A pairing.  Cross-checked against FFTriadBuddy's
# reference implementation (TriadGameModifierFallenAce, sources/gamelogic/
# TriadGameModifier.cs): whichever side is the ATTACKER in a printed 1-vs-A
# matchup always captures the other - in both normal and Reverse play.
#
# Without Reverse: a placed 1 gains the ability to capture a defending A
# (ordinarily impossible, 1 < 10); a placed A capturing a defending 1 already
# happens under plain higher-wins, so Fallen Ace doesn't need to touch it.
# With Reverse: the roles swap - a placed A gains the ability to capture a
# defending 1 (ordinarily impossible once lower wins), while a placed 1
# capturing a defending A already happens under reversed math.  Net effect
# either way: the attacker wins a 1-vs-A pairing, full stop.


def _type_count(board, kind: str) -> int:
    return sum(1 for s in board if s is not None and CARDS[s[0]].kind == kind)


def kind_counts(board) -> dict[str, int]:
    """Every faction's card count on ``board``, in a single pass.

    Resolution only ever flips owners - it never adds, removes or changes a card -
    so these counts are constant for a whole ``_resolve`` and can be computed once
    and shared by every ``eff`` call instead of rescanning the board per query.
    """
    counts: dict[str, int] = {}
    for s in board:
        if s is not None:
            k = CARDS[s[0]].kind
            if k != "None":
                counts[k] = counts.get(k, 0) + 1
    return counts


def eff(rules: RuleSet, board, cell: int, d: int, *, placed_kind: str | None = None,
        counts: dict[str, int] | None = None) -> int:
    """Effective value of ``board[cell]``'s side ``d`` given the current board.

    Pass ``placed_kind`` (the faction of the card being placed this turn) while
    resolving a placement: cards of that faction don't yet count the just-placed
    card toward their total, so a printed value is compared using the
    pre-placement faction count.

    ``counts`` is an optional prebuilt ``kind_counts(board)``; supply it to avoid
    rescanning the board on every call.
    """
    card = CARDS[board[cell][0]]
    v = card.sides[d]
    kind = card.kind
    if (rules.ascension or rules.descension) and kind != "None":
        n = _type_count(board, kind) if counts is None else counts.get(kind, 0)
        if kind == placed_kind:           # the card just placed isn't counted yet
            n -= 1
        if rules.descension:
            v = max(1, v - n)
        else:
            v = min(_ASCENSION_MAX, v + n)
    return v


def attacker_wins(rules: RuleSet, ea: int, ed: int, pa: int, pd: int) -> bool:
    """Ordinary capture test: attacker side vs defender side.

    ``ea``/``ed`` are effective values (Ascension applied); ``pa``/``pd`` are the
    printed values, used only to detect the Fallen Ace pairing.
    """
    if rules.fallen_ace and ((pa == 10 and pd == 1) or (pa == 1 and pd == 10)):
        return True
    return (ea < ed) if rules.reverse else (ea > ed)


def resolve_placement(rules: RuleSet, board: tuple, cell: int):
    """Public: resolve the card already sitting at ``board[cell]``.

    Returns ``(new_board_tuple, log)`` where ``log`` records which cells were
    flipped by Same / Plus / an ordinary capture / Combo.
    """
    b = list(board)
    log = {"placed": cell, "same": [], "plus": [], "basic": [], "combo": []}
    _resolve(rules, b, cell, log)
    return tuple(b), log


def _resolve(rules: RuleSet, b: list, cell: int, log=None) -> None:
    """Core resolver: mutates the board list ``b`` in place.  Fills ``log`` only
    when one is supplied (the solver's hot path passes none)."""
    owner = b[cell][1]
    psides = CARDS[b[cell][0]].sides
    asc = rules.ascension or rules.descension
    plain = not rules.reverse and not rules.fallen_ace   # ordinary "higher wins"
    placed_kind = CARDS[b[cell][0]].kind                 # excluded from faction counts this turn

    # occupied neighbours as (dir, cell, defender facing value)
    occ = []
    for d, nc in NEIGHBORS[cell]:
        t = b[nc]
        if t is not None:
            occ.append((d, nc, CARDS[t[0]].sides[OPP[d]]))
    if asc:
        # card ids are fixed for the whole resolution, so count factions once
        counts = kind_counts(b)
        # all four sides of the placed card share one faction adjustment (and it
        # never counts itself), so shift them directly instead of per-side eff()
        n = 0 if placed_kind == "None" else counts.get(placed_kind, 0) - 1
        if n == 0:
            pe = psides
        elif rules.descension:
            pe = tuple(max(1, v - n) for v in psides)
        else:
            pe = tuple(min(_ASCENSION_MAX, v + n) for v in psides)
        occ = [(d, nc, eff(rules, b, nc, OPP[d], placed_kind=placed_kind, counts=counts))
               for (d, nc, _v) in occ]
    else:
        counts = None
        pe = psides

    same_caps = ()
    if rules.same:
        hits, cnt = [], 0
        for d, nc, dv in occ:
            if pe[d] == dv:
                hits.append(nc)
                cnt += 1
        if rules.same_wall:
            for d in WALLS[cell]:
                if pe[d] == 10:
                    cnt += 1
        if cnt >= 2:
            same_caps = [nc for nc in hits if b[nc][1] != owner]

    plus_caps = ()
    if rules.plus:
        buckets: dict[int, list[int]] = {}
        for d, nc, dv in occ:
            k = pe[d] + dv
            r = buckets.get(k)
            if r is None:
                buckets[k] = [nc]
            else:
                r.append(nc)
        pc = []
        for ncs in buckets.values():
            if len(ncs) >= 2:
                pc += [nc for nc in ncs if b[nc][1] != owner]
        plus_caps = pc

    basic = []
    for d, nc, dv in occ:
        if b[nc][1] != owner:
            a = pe[d]
            if plain:
                win = a > dv
            elif asc:                    # an ascended "A" (capped at 10) counts as A
                win = attacker_wins(rules, a, dv, a, dv)
            else:
                win = attacker_wins(rules, a, dv, psides[d], CARDS[b[nc][0]].sides[OPP[d]])
            if win:
                basic.append(nc)

    if not same_caps and not plus_caps and not basic:
        return
    seed = set(same_caps)
    seed.update(plus_caps)
    flipped = seed.union(basic)
    for nc in flipped:
        b[nc] = (b[nc][0], owner)
    if log is not None:
        log["same"] = sorted(same_caps)
        log["plus"] = sorted(plus_caps)
        log["basic"] = sorted(set(basic) - seed)

    # Combo: only Same/Plus flips seed a cascade; ordinary captures do not
    if seed:
        q = deque(seed)
        while q:
            src = q.popleft()
            ss = CARDS[b[src][0]].sides
            for d, nc in NEIGHBORS[src]:
                t = b[nc]
                if t is not None and t[1] != owner:
                    dv = CARDS[t[0]].sides[OPP[d]]
                    if asc:
                        av = eff(rules, b, src, d, placed_kind=placed_kind, counts=counts)
                        xv = eff(rules, b, nc, OPP[d], placed_kind=placed_kind, counts=counts)
                        win = (av > xv) if plain else attacker_wins(rules, av, xv, av, xv)
                    else:
                        av = ss[d]
                        win = (av > dv) if plain else attacker_wins(rules, av, dv, av, dv)
                    if win:
                        b[nc] = (t[0], owner)
                        if log is not None:
                            log["combo"].append(nc)
                        q.append(nc)
