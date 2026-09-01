"""Alpha-beta solver.  The game is only 9 plies deep, so every line is searched
to a full board and scored by the real card margin - there is no heuristic
evaluation.

Player A (owner 0, "you") maximises the margin; player B (the NPC) minimises.
``analyze()`` reports the move for whichever side is to move.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .data import CARDS, deck_draw, is_variable_deck, load_decks, load_npcs, find_npc, resolve
from .model import (
    EMPTY_BOARD, NEIGHBORS, OPP, GameState, RuleSet,
    is_terminal, value_a,
)
from .regions import effective_rules
from .rules import _resolve

INF = 10 ** 9
CELL_PRIORITY = (4, 0, 2, 6, 8, 1, 3, 5, 7)
CELL_RANK = {c: i for i, c in enumerate(CELL_PRIORITY)}
_EXACT, _LOWER, _UPPER = 0, 1, 2


def legal_moves(state: GameState):
    """(hand_index, cell) pairs.  Identical cards in hand are collapsed; Order
    forces the first hand card; the empty opening board is reduced to one
    representative per symmetry class (corner / edge / centre)."""
    hand = state.hands[state.to_move]
    if not hand:
        return []
    cells = [i for i in range(9) if state.board[i] is None]
    if len(cells) == 9:
        cells = [0, 1, 4]
    if state.rules.order:
        idxs = [0]
    else:
        seen, idxs = set(), []
        for i, cid in enumerate(hand):
            if cid not in seen:
                seen.add(cid)
                idxs.append(i)
    return [(i, c) for i in idxs for c in cells]


def apply(state: GameState, hand_idx: int, cell: int) -> GameState:
    owner = state.to_move
    cid = state.hands[owner][hand_idx]
    b = list(state.board)
    b[cell] = (cid, owner)
    _resolve(state.rules, b, cell)
    nb = tuple(b)
    h = state.hands[owner]
    nh = h[:hand_idx] + h[hand_idx + 1:]
    hands = (nh, state.hands[1]) if owner == 0 else (state.hands[0], nh)
    return GameState(nb, hands, 1 - owner, state.rules)


def _quick_gain(board, sides, owner: int, cell: int) -> int:
    """Cheap ordering score: neighbours the placed card out-numbers on the touching
    side.  Ignores Reverse / Fallen Ace / Ascension - it only has to sort moves."""
    g = 0
    for d, nc in NEIGHBORS[cell]:
        s = board[nc]
        if s is not None and s[1] != owner and sides[d] > CARDS[s[0]].sides[OPP[d]]:
            g += 1
    return g


def _ordered(state: GameState, filled: int):
    ms = legal_moves(state)
    if len(ms) <= 1:
        return ms
    if filled >= 6:                       # last few plies: subtrees are tiny, skip the gain calc
        ms.sort(key=lambda m: CELL_RANK[m[1]])
        return ms
    board, hand = state.board, state.hands[state.to_move]
    owner = state.to_move
    ms.sort(key=lambda m: (-_quick_gain(board, CARDS[hand[m[0]]].sides, owner, m[1]),
                           CELL_RANK[m[1]]))
    return ms


class _Ctx:
    __slots__ = ("tt", "killers", "opp")

    def __init__(self, opp: str = "optimal"):
        self.tt: dict = {}
        self.killers: dict = {}          # board-fill count -> (hand_idx, cell)
        self.opp = opp                   # NPC model: "optimal" | "greedy"

    def __len__(self):                   # reported as "positions searched"
        return len(self.tt)


def _margin(state: GameState) -> int:
    a = b = 0
    for s in state.board:
        if s is not None:
            if s[1] == 0:
                a += 1
            else:
                b += 1
    return a - b


def npc_move(state: GameState):
    """The modelled NPC move: take the most cards right now; among ties, keep the
    placed card's strongest sides facing open cells; then board centre.  This is
    roughly how the in-game AI plays - far from optimal, and exploitable."""
    owner = state.to_move
    board = state.board
    best_key = best_mv = None
    for hi, ce in legal_moves(state):
        sides = CARDS[state.hands[owner][hi]].sides
        gain = _margin(apply(state, hi, ce))
        gain = gain if owner == 0 else -gain
        safe = sum(sides[d] for d, nc in NEIGHBORS[ce] if board[nc] is None)
        key = (gain, safe, -CELL_RANK[ce])
        if best_key is None or key > best_key:
            best_key, best_mv = key, (hi, ce)
    return best_mv


def _heur(state: GameState) -> int:
    """Depth-limit stand-in for a terminal score: current board margin, scaled
    like value_a (positive = A ahead)."""
    a = sum(1 for s in state.board if s is not None and s[1] == 0)
    b = sum(1 for s in state.board if s is not None and s[1] == 1)
    return 2 * (a - b)


def _chaos_value(state: GameState, ctx: _Ctx, depth=None) -> float:
    """Expectimax node: under Chaos the mover picks only the cell; the card is a
    uniform draw from the hand.  Searched on a full window (no pruning).

    Every ply is such a node when Chaos is live, so alpha-beta never gets a turn
    and the raw tree is ~28x bigger per empty cell.  The saving grace is that the
    value here is window-independent - a plain expectation, not a bound - so it
    memoises unconditionally, and Chaos positions transpose heavily (the same
    board arrives via many play orders).  The transposition table is what makes a
    full-board Chaos solve finish at all."""
    exact = depth is None
    if exact:
        key = state.key()
        hit = ctx.tt.get(key)
        if hit is not None:
            return hit[0]
    hand = state.hands[state.to_move]
    cells = [i for i in range(9) if state.board[i] is None]
    if len(cells) == 9:
        cells = [0, 1, 4]
    maximizing = state.to_move == 0
    total = len(hand)
    exp = 0.0
    for cid, k in Counter(hand).items():
        hi = hand.index(cid)
        outs = [_search(apply(state, hi, c), -INF, INF, ctx, depth) for c in cells]
        exp += (k / total) * (max(outs) if maximizing else min(outs))
    if exact:
        ctx.tt[key] = (exp, _EXACT)
    return exp


def _search(state: GameState, alpha: int, beta: int, ctx: _Ctx, depth=None):
    if is_terminal(state):
        return value_a(state)
    if depth is not None and depth <= 0:
        return _heur(state)
    if state.rules.chaos and state.hands[state.to_move]:
        return _chaos_value(state, ctx, depth)
    nd = None if depth is None else depth - 1

    # modelled (non-optimal) NPC: play its single policy move, don't branch
    if ctx.opp != "optimal" and state.to_move == 1:
        mv = npc_move(state)
        return value_a(state) if mv is None else _search(apply(state, *mv), alpha, beta, ctx, nd)

    exact = depth is None
    key = state.key()
    a0, b0 = alpha, beta
    hit = ctx.tt.get(key) if exact else None
    if hit is not None:
        v, flag = hit
        if flag == _EXACT:
            return v
        if flag == _LOWER:
            alpha = max(alpha, v)
        else:
            beta = min(beta, v)
        if alpha >= beta:
            return v

    filled = 9 - state.board.count(None)
    moves = _ordered(state, filled)
    km = ctx.killers.get(filled)
    if km is not None and km in moves:
        moves.remove(km)
        moves.insert(0, km)

    maximizing = state.to_move == 0
    best = -INF if maximizing else INF
    for i, m in enumerate(moves):
        child = apply(state, *m)
        if i == 0:
            v = _search(child, alpha, beta, ctx, nd)
        elif maximizing:                       # principal-variation search
            v = _search(child, alpha, alpha + 1, ctx, nd)
            if alpha < v < beta:
                v = _search(child, v, beta, ctx, nd)
        else:
            v = _search(child, beta - 1, beta, ctx, nd)
            if alpha < v < beta:
                v = _search(child, alpha, v, ctx, nd)
        if maximizing:
            if v > best:
                best = v
            alpha = max(alpha, best)
        else:
            if v < best:
                best = v
            beta = min(beta, best)
        if alpha >= beta:
            ctx.killers[filled] = m
            break

    if exact:
        flag = _EXACT if a0 < best < b0 else (_UPPER if best <= a0 else _LOWER)
        ctx.tt[key] = (best, flag)
    return best


def solve(state: GameState, opp: str = "optimal") -> int:
    """Exact game value from A's perspective (positive = A ahead), searched to a
    full board.  ``opp`` is the NPC model: "optimal" (minimax) or "greedy"."""
    if is_terminal(state):
        return value_a(state)
    return _search(state, -INF, INF, _Ctx(opp))


@dataclass
class RankedMove:
    hand_idx: int
    cell: int
    card: object          # Card
    value: float          # margin from A's perspective under optimal play


@dataclass
class Analysis:
    state: GameState
    best: RankedMove
    ranked: list          # all root moves, best first for the side to move
    pv: list              # [(RankedMove-ish, GameState), ...] optimal continuation
    tt_size: int

    @property
    def margin(self) -> float:
        """Final card margin for the side to move (positive = that side wins)."""
        return self.best.value if self.state.to_move == 0 else -self.best.value

    @property
    def outcome(self) -> str:
        m = self.margin
        return "win" if m > 0 else "loss" if m < 0 else "draw"


def analyze(state: GameState, forced_hand_idx: int | None = None,
            opp: str = "optimal") -> Analysis:
    """Rank the moves for the side to move.

    ``opp`` picks the NPC model: "optimal" plays perfect minimax (safe, often
    pessimistic); "greedy" plays the in-game-style 1-ply capture-grabber, giving
    an exploitative move and a realistic margin.

    Under Chaos the mover cannot choose which card is played, so pass
    ``forced_hand_idx`` (the card the game dealt this turn); the ranking is then
    over cells only.  The opponent's Chaos turns are always modelled as
    expectimax inside the search.
    """
    if is_terminal(state):
        raise ValueError("board is full")
    if state.rules.chaos and forced_hand_idx is None:
        raise ValueError("Chaos is active: pass forced_hand_idx (the card you were dealt)")
    ctx = _Ctx(opp)
    maximizing = state.to_move == 0
    if forced_hand_idx is not None:
        cells = [i for i in range(9) if state.board[i] is None]
        if len(cells) == 9:
            cells = [0, 1, 4]
        root = [(forced_hand_idx, c) for c in cells]
    elif opp != "optimal" and state.to_move == 1:
        root = [npc_move(state)]                 # NPC plays its one modelled move
    else:
        root = _ordered(state, 9 - state.board.count(None))
    ranked = []
    for hi, ce in root:
        v = _search(apply(state, hi, ce), -INF, INF, ctx)
        ranked.append(RankedMove(hi, ce, CARDS[state.hands[state.to_move][hi]], v))
    ranked.sort(key=lambda r: r.value, reverse=maximizing)

    pv, cur = [], state
    while not is_terminal(cur):
        if cur.rules.chaos:
            break
        step = _best_child(cur, ctx)
        if step is None:
            break
        mv, nxt = step
        pv.append((mv, nxt))
        cur = nxt
    return Analysis(state, ranked[0], ranked, pv, len(ctx))


def _best_child(state: GameState, ctx: "_Ctx"):
    maximizing = state.to_move == 0
    if ctx.opp != "optimal" and state.to_move == 1:
        mv = npc_move(state)
        if mv is None:
            return None
        nxt = apply(state, *mv)
        rm = RankedMove(mv[0], mv[1], CARDS[state.hands[1][mv[0]]], _search(nxt, -INF, INF, ctx))
        return (rm, nxt)
    best_mv = best_st = None
    best_val = -INF if maximizing else INF
    for hi, ce in _ordered(state, 9 - state.board.count(None)):
        nxt = apply(state, hi, ce)
        v = _search(nxt, -INF, INF, ctx)
        if (v > best_val) if maximizing else (v < best_val):
            best_val = v
            best_mv = RankedMove(hi, ce, CARDS[state.hands[state.to_move][hi]], v)
            best_st = nxt
    return None if best_mv is None else (best_mv, best_st)


# --- building a match from the dataset ------------------------------------

def new_match(npc: str, your_deck, you_first: bool = True,
              npc_deck=None, rules=None, use_regional: bool = True) -> GameState:
    npcs = load_npcs()
    rec = find_npc(npc, npcs)
    decks = load_decks()
    entry = decks.get(rec["name"], {})
    if npc_deck is None:
        npc_deck = entry.get("cards")
    if not npc_deck and is_variable_deck(entry):
        raise ValueError(
            f"{rec['name']!r} draws {deck_draw(entry)} of "
            f"[{', '.join(entry['pool'])}] on top of {', '.join(entry['fixed'])}; "
            f"pass the actual 5 via npc_deck / --npc-deck"
        )
    if not npc_deck:
        raise ValueError(
            f"no deck recorded for {rec['name']!r} - add it with "
            f"scripts/deck.py add {rec['name']!r} <5 cards>"
        )
    rnames = effective_rules(rec, deck_entry=entry, override=rules,
                             use_regional=use_regional)
    rs = RuleSet.from_names(rnames)
    a = tuple(resolve(x).id for x in your_deck)
    b = tuple(resolve(x).id for x in npc_deck)
    if len(a) != 5 or len(b) != 5:
        raise ValueError("each deck must have exactly 5 cards")
    return GameState(EMPTY_BOARD, (a, b), 0 if you_first else 1, rs)
