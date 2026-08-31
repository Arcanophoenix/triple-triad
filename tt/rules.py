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
# gives every card of that faction +1 / -1, stacking, the just-placed card
# included.  So N faction cards on the board => +/-N.  Ascension results of "11"
# or higher are treated as an "A" (capped at 10); Descension results of "0" or
# less are treated as a "1".
_ASCENSION_MAX = 10

# Fallen Ace, the 1-vs-A pairing.  Wiki: "the all-powerful 'A' becomes
# susceptible to capture by the lowly '1.'  If the 'Reverse' rule is also in
# play, a '1' will then become vulnerable to capture by an 'A.'"
#   "hard" - that pairing's outcome is fixed regardless of who placed the card,
#            and Reverse inverts it.  (Matches the wiki wording.)
#   "vuln" - Fallen Ace only ADDS "a placed 1 captures an A"; a placed A still
#            captures a 1 normally.  VERIFY: only the placed-A-onto-1 sub-case
#            distinguishes the two, and the wiki doesn't spell it out.
FALLEN_ACE_MODE = "hard"


def _type_count(board, kind: str) -> int:
    return sum(1 for s in board if s is not None and CARDS[s[0]].kind == kind)


def eff(rules: RuleSet, board, cell: int, d: int) -> int:
    """Effective value of ``board[cell]``'s side ``d`` given the current board."""
    card = CARDS[board[cell][0]]
    v = card.sides[d]
    if (rules.ascension or rules.descension) and card.kind != "None":
        n = _type_count(board, card.kind)          # faction cards on the board, self included
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
    if rules.fallen_ace and ((pa == 10 and pd == 1) or (pd == 10 and pa == 1)):
        one_beats_ace = not rules.reverse          # Reverse cancels Fallen Ace here
        attacker_has_one = pa == 1
        if FALLEN_ACE_MODE == "vuln" and not attacker_has_one:
            return (ea < ed) if rules.reverse else (ea > ed)
        return one_beats_ace if attacker_has_one else not one_beats_ace
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

    # occupied neighbours as (dir, cell, defender facing value)
    occ = []
    for d, nc in NEIGHBORS[cell]:
        t = b[nc]
        if t is not None:
            occ.append((d, nc, CARDS[t[0]].sides[OPP[d]]))

    if asc:
        pe = (eff(rules, b, cell, 0), eff(rules, b, cell, 1),
              eff(rules, b, cell, 2), eff(rules, b, cell, 3))
        occ = [(d, nc, eff(rules, b, nc, OPP[d])) for (d, nc, _v) in occ]
    else:
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
                        av, xv = eff(rules, b, src, d), eff(rules, b, nc, OPP[d])
                        win = (av > xv) if plain else attacker_wins(rules, av, xv, av, xv)
                    else:
                        av = ss[d]
                        win = (av > dv) if plain else attacker_wins(rules, av, dv, av, dv)
                    if win:
                        b[nc] = (t[0], owner)
                        if log is not None:
                            log["combo"].append(nc)
                        q.append(nc)
