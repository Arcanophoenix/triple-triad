"""Deck recommender.

A full solve per candidate deck is far too slow (thousands of ~20 s opening
solves), so this works in two passes:

1. **screen** every constraint-legal 5-card deck from a heuristic shortlist with a
   fast 1-ply greedy playout (both coin-toss orientations);
2. **exact-solve** the top slice with the real alpha-beta solver.

Decks are ranked by the worst of the two coin-toss outcomes, then by the average
margin.  The margin is always from your perspective (positive = you win).

Under the **Order** rule the hand is played strictly left-to-right, so a deck's
arrangement is itself a decision - the same five cards can win in one order and
lose in another.  Screening picks the greedy-best order per deck; the exact pass
then re-solves the most promising orderings and returns the winning one.  The
recommended ``DeckResult.cards`` is therefore the exact left-to-right sequence to
set in-game.
"""
from __future__ import annotations

import multiprocessing
import os
import warnings
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from itertools import combinations, permutations

# Workers are forked: they inherit the loaded card dataset (and any test cards),
# start instantly, and never re-import __main__ - which keeps this working when
# the caller is a threaded HTTP server, a runpy'd script, or a heredoc.  They do
# pure arithmetic on read-only data straight after the fork, so the multi-thread
# fork warning does not apply here.
warnings.filterwarnings("ignore", message=r".*multi-threaded.*fork\(\).*",
                        category=DeprecationWarning)

from .data import CARDS, Card
from .model import EMPTY_BOARD, GameState, RuleSet, is_terminal, value_a
from .rules import _resolve
from .solver import apply, legal_moves, solve

HIGH_RARITY = 4          # cards at >= this many stars are deck-limited
MAX_HIGH_PER_DECK = 1    # VERIFY: standard decks allow one 4/5-star card


# --- heuristic card score (only used to pick the shortlist) ----------------

def card_score(c: Card, rules: RuleSet) -> float:
    s = c.sides
    total = sum(s)
    adj = (s[0] + s[1], s[1] + s[2], s[2] + s[3], s[3] + s[0])  # corner pairs
    if rules.reverse:
        base = 44 - total + 0.5 * (20 - min(adj))
    else:
        base = total + 1.5 * sum(v == 10 for v in s) + 0.5 * max(adj)
    if rules.fallen_ace:
        # Fallen Ace doesn't make low cards good in general - it only lets the
        # weak number in a 1-vs-A pairing capture the strong one (Reverse swaps
        # which is which).  So the weak number gains threat value, the strong
        # one becomes a small liability.
        weak, strong = (10, 1) if rules.reverse else (1, 10)
        base += 3 * sum(v == weak for v in s) - 2 * sum(v == strong for v in s)
    if (rules.ascension or rules.descension) and c.kind != "None":
        base += 3 if rules.ascension else -1
    if rules.same or rules.plus:
        base += 0.5 * (4 - len(set(s)))
    return base


def shortlist(pool: list[int], rules: RuleSet, n: int) -> list[int]:
    """Top ``n`` cards by heuristic, but reserve room for low-rarity cards so a
    legal deck can always be built (a deck needs >=4 cards below the high-rarity
    limit)."""
    ranked = sorted(pool, key=lambda i: card_score(CARDS[i], rules), reverse=True)
    highs = [i for i in ranked if CARDS[i].stars >= HIGH_RARITY]
    lows = [i for i in ranked if CARDS[i].stars < HIGH_RARITY]
    keep_high = highs[:max(MAX_HIGH_PER_DECK * 3, 1)] if MAX_HIGH_PER_DECK else []
    keep_low = lows[:max(n - len(keep_high), 4)]
    return keep_high + keep_low


def legal_decks(pool: list[int]):
    """All 5-card combinations from ``pool`` obeying the high-rarity limit."""
    highs = [i for i in pool if CARDS[i].stars >= HIGH_RARITY]
    lows = [i for i in pool if CARDS[i].stars < HIGH_RARITY]
    for combo in combinations(lows, 5):
        yield combo
    if MAX_HIGH_PER_DECK:
        for h in highs:
            for combo in combinations(lows, 4):
                yield (h,) + combo


# --- fast screening: greedy opening, then an exact endgame ----------------

def _margin_after(state: GameState, hand_idx: int, cell: int) -> int:
    """Board margin (A minus B) after playing ``(hand_idx, cell)``.

    Resolves the board only: ``_greedy_step`` scores every legal move and then
    throws all but one away, so building a full successor GameState (hand
    slicing, dataclass construction) for each candidate is wasted work.
    """
    owner = state.to_move
    b = list(state.board)
    b[cell] = (state.hands[owner][hand_idx], owner)
    _resolve(state.rules, b, cell)
    a = n = 0
    for s in b:
        if s is not None:
            if s[1] == 0:
                a += 1
            else:
                n += 1
    return a - n


def _greedy_step(state: GameState) -> GameState:
    """Apply the move that most improves the mover's board margin (1-ply, myopic)."""
    want_max = state.to_move == 0
    best_m, best_v = None, None
    for m in legal_moves(state):
        v = _margin_after(state, *m)
        v = v if want_max else -v
        if best_v is None or v > best_v:
            best_v, best_m = v, m
    return apply(state, *best_m) if best_m is not None else state


def greedy_playout(state: GameState) -> int:
    # not is_terminal => a free cell and cards in hand => legal_moves is non-empty,
    # so there is no need to build the move list just to test it
    s = state
    while not is_terminal(s):
        s = _greedy_step(s)
    return value_a(s)


def screen_value(state: GameState, tail: int = 6, opp: str = "optimal") -> int:
    """Screening estimate: play the opening with the greedy policy, then solve the
    last ``tail`` plies exactly (against the ``opp`` model).  A real terminal
    margin - board-margin at any earlier point is nearly meaningless in Triple
    Triad, so a fixed shallow search is a poor proxy; a short exact endgame is a
    good one."""
    s = state
    limit = 9 - tail
    while not is_terminal(s) and 9 - s.board.count(None) < limit:
        s = _greedy_step(s)
    return solve(s, opp)


# --- results ------------------------------------------------------------

@dataclass
class DeckResult:
    cards: tuple                # card ids
    first: float                # your margin going first
    second: float               # your margin going second
    exact: bool = False         # solved to terminal (vs greedy estimate)

    @property
    def worst(self) -> float:
        return min(self.first, self.second)

    @property
    def avg(self) -> float:
        return (self.first + self.second) / 2

    def names(self) -> list[str]:
        return [CARDS[i].name for i in self.cards]


@dataclass
class Recommendation:
    npc: str
    rules: RuleSet
    npc_deck: tuple
    screened: int
    results: list                      # DeckResult, best first
    # (slot, out_name, in_name, delta) - deck-editing advice, NOT the Swap rule
    swaps: list = field(default_factory=list)

    @property
    def best(self) -> DeckResult:
        return self.results[0]


# --- orchestration -----------------------------------------------------

ORDER_PROBE = 12         # hand orderings exact-solved per deck under the Order rule
# Swap outcomes sampled per NPC draw during the *coarse* screen only.  There are
# 25 (5x5); _matchups emits them stratified by which of YOUR cards is given up, so
# the first 5 already cover every slot of yours once.  All 24 Swap NPCs also have
# variable decks, so scoring the full 25 across the whole candidate field is far
# too slow - but a truncated sample must never decide the final answer: taking the
# best of hundreds of noisy averages is a winner's curse and reads optimistic
# (measured: the top deck's margin drifts from +2.0 at 1 sample to -2.2 at all 25).
# So this only narrows the field; every later phase re-scores on all 25.
SWAP_PROBE = 5
# Plies solved exactly at the end of a Chaos evaluation.  Chaos is the one rule
# whose positions cannot be solved to a full board: every ply is an expectimax
# node, alpha-beta never gets a window to prune on, and the cost runs ~0.2s at six
# empty cells, ~4s at seven, minutes at eight.  So the "exact" pass deepens the
# screen instead of solving outright, and says so (DeckResult.exact is False under
# Chaos).  6 is the sweet spot: against a tail-7 reference it lands within 0.29 on
# average, where tail 7 itself costs 17x and the old single-greedy-playout fallback
# was out by 1.88 on average and 3.46 at worst - and always in our favour.
CHAOS_TAIL = 6


def _key(deck, npc_deck, side, ordered=False):
    our = tuple(deck) if ordered else tuple(sorted(deck))
    return (our, tuple(sorted(npc_deck)), side)


def _matchups(deck, npc_deck, rules, limit: int = 0) -> list[tuple]:
    """The ``(your hand, their hand)`` pairs a match can actually start from.

    Without Swap that is just the two decks as chosen.  Under **Swap** the game
    exchanges one random card from each deck before play ("the cards to be
    swapped are chosen at random... rarity is ignored"), so the deck you pick is
    never the hand you play: all 5x5 pairings are equally likely and the deck has
    to be judged across them.  The swapped-in card takes the slot of the card it
    replaced, which is what keeps this correct under Order.

    Pairs are emitted stratified by *which of your cards you give up* - the
    dominant source of variance, since losing your best card hurts far more than
    which of theirs you happen to receive.  So a truncated sample (``limit``)
    still covers every one of your slots before it repeats any.  ``limit=0``
    yields all 25.
    """
    if not rules.swap:
        return [(tuple(deck), tuple(npc_deck))]
    d, n = list(deck), list(npc_deck)
    out = []
    for off in range(len(n)):
        for i in range(len(d)):
            j = (i + off) % len(n)
            mine, theirs = d.copy(), n.copy()
            mine[i], theirs[j] = n[j], d[i]
            out.append((tuple(mine), tuple(theirs)))
    return out[:limit] if limit else out


def _avg_sides(deck, npc_deck, rules, evaluate, limit: int = 0):
    """``(first, second)`` margins for ``deck`` against one NPC draw.

    ``evaluate(state) -> margin``.  Under Swap the outcomes are **averaged**, not
    worst-cased: the exchange is random and you cannot influence it, so the
    honest number is its expectation.  Worst-casing a coin you don't get to flip
    would rate every deck by its unluckiest swap and flatten the ranking.
    """
    pairs = _matchups(deck, npc_deck, rules, limit)
    firsts = seconds = 0.0
    for mine, theirs in pairs:
        hands = (mine, theirs)
        firsts += evaluate(GameState(EMPTY_BOARD, hands, 0, rules))
        seconds += evaluate(GameState(EMPTY_BOARD, hands, 1, rules))
    n = len(pairs)
    return firsts / n, seconds / n


def _order_variants(deck) -> list[tuple]:
    """Every distinct hand ordering of ``deck`` (fewer than 120 when a card repeats)."""
    return list(dict.fromkeys(permutations(deck)))


def _greedy_order_key(perm, npc_decks, rules):
    """(worst-case, average) margin for one fixed hand order under a pure greedy
    playout - cheap enough to rank all 120 orderings of a deck.

    Deliberately swap-blind: this only *ranks* orderings, and folding the 25 Swap
    outcomes in here would multiply the 120-permutation sweep by 25.  A swap
    leaves four of the five cards in place, so the un-swapped hand is a fair proxy
    for which sequences are worth an exact solve - and those solves are swap-aware.
    """
    f = min(greedy_playout(GameState(EMPTY_BOARD, (perm, nd), 0, rules)) for nd in npc_decks)
    s = min(greedy_playout(GameState(EMPTY_BOARD, (perm, nd), 1, rules)) for nd in npc_decks)
    return (min(f, s), (f + s) / 2)


def _screen_order(deck, npc_decks, rules) -> tuple:
    """The single hand order to screen ``deck`` in: the deck as given unless Order
    is live, in which case the greedy-best ordering - so a strong deck is not
    filtered out for a bad arrangement before the exact pass can reorder it."""
    if not rules.order:
        return tuple(deck)
    return max(_order_variants(deck), key=lambda p: _greedy_order_key(p, npc_decks, rules))


def _probe_orders(deck, npc_decks, rules, keep=ORDER_PROBE) -> list[tuple]:
    """Hand orderings worth an exact solve.  Not Order: just the deck.  Order:
    the ``keep`` orderings that look best under a greedy playout (exact-solving all
    120 is wasteful and the greedy ranking puts the true best near the top)."""
    if not rules.order:
        return [tuple(deck)]
    variants = _order_variants(deck)
    if len(variants) <= keep:
        return variants
    variants.sort(key=lambda p: _greedy_order_key(p, npc_decks, rules), reverse=True)
    return variants[:keep]


def _pick_best(results):
    """The DeckResult with the best (worst-case, average) margin."""
    return max(results, key=lambda r: (r.worst, r.avg))


def _screen(deck, npc_deck, rules, cache, tail=6, opp="optimal", swap_probe=0):
    def ev(st):
        k = (tail, opp, *_key(st.hands[0], st.hands[1], st.to_move, rules.order))
        if k not in cache:
            cache[k] = screen_value(st, tail, opp)
        return cache[k]
    first, second = _avg_sides(deck, npc_deck, rules, ev, swap_probe)
    return DeckResult(tuple(deck), first, second, exact=False)


def _exact_value(st, rules, opp):
    """The exact pass's value for one opening.

    Normally a full-board solve.  ``solve`` rather than ``analyze(st).best.value``:
    the two agree exactly - analyze's ranking maximum *is* the game value - but
    analyze searches every root move on a full window in order to rank them all,
    while the recommender only wants the number.  Measured 5.2x faster over 24
    openings across Plain/Plus/Same/Ascension/Reverse+Fallen Ace/Order, both NPC
    models and both sides, with identical values.

    Chaos is the exception, and the reason this is a function: ``analyze`` cannot
    rank moves you do not get to choose, so it raises there.  A full solve is out
    of reach too (see CHAOS_TAIL), so Chaos deepens the screen instead - greedy
    opening, then an exact Chaos-aware expectimax tail."""
    if rules.chaos:
        return screen_value(st, CHAOS_TAIL, opp)
    return solve(st, opp)


def _exact_tag(rules) -> bool:
    """Whether an exact-pass result really was solved to a full board.  False under
    Chaos, where the pass is a deep estimate - claiming otherwise would put an
    unearned `(est)`-free guarantee on 21 NPCs' recommendations."""
    return not rules.chaos


def _exact(deck, npc_deck, rules, cache, opp="optimal", swap_probe=0):
    # under Chaos this shares the screen's cache entries when the tails coincide
    tag = CHAOS_TAIL if rules.chaos else "x"

    def ev(st):
        k = (tag, opp, *_key(st.hands[0], st.hands[1], st.to_move, rules.order))
        if k not in cache:
            cache[k] = _exact_value(st, rules, opp)
        return cache[k]
    first, second = _avg_sides(deck, npc_deck, rules, ev, swap_probe)
    return DeckResult(tuple(deck), first, second, exact=_exact_tag(rules))


def _normalize_npc_decks(npc_deck) -> list[tuple]:
    """Accept a single deck (list of card ids) or a list of decks (for an NPC
    whose deck is only known up to a random draw); return a list of id-tuples."""
    seq = list(npc_deck)
    if seq and isinstance(seq[0], int):
        return [tuple(seq)]
    return [tuple(d) for d in seq]


def _hardest_npc_deck(npc_decks, rules: RuleSet) -> tuple:
    """The single toughest-looking draw, used as a stand-in when screening the
    whole candidate field (screening against every possible draw is the same work
    times len(npc_decks)).  "Toughest" = most raw stat total, flipped under
    Reverse where low sides win.  (Fallen Ace alone doesn't flip it - high sides
    still win everything outside the 1-vs-A pairing.)"""
    low = rules.reverse
    def strength(nd):
        t = sum(sum(CARDS[c].sides) for c in nd)
        return -t if low else t
    return max(npc_decks, key=strength)


def _screen_any(deck, npc_decks, rules, cache, tail=6, opp="optimal", swap_probe=0):
    """Screen ``deck`` against every possible NPC deck; keep the worst side-margins.
    Under Order the deck is screened in its greedy-best arrangement.  The two
    kinds of uncertainty are aggregated differently: their random *draw* is
    worst-cased (a safety floor), the random *swap* is averaged (see _avg_sides)."""
    deck = _screen_order(deck, npc_decks, rules)
    parts = [_screen(deck, nd, rules, cache, tail, opp, swap_probe) for nd in npc_decks]
    return DeckResult(tuple(deck), min(p.first for p in parts),
                      min(p.second for p in parts), exact=False)


def _exact_any(deck, npc_decks, rules, cache, opp="optimal", order_keep=ORDER_PROBE,
               swap_probe=0):
    """Exact-solve ``deck`` vs every possible NPC deck.  Under Order the promising
    hand orderings are each solved and the best-scoring one is returned, so
    ``.cards`` is the arrangement to play."""
    best = None
    for perm in _probe_orders(deck, npc_decks, rules, order_keep):
        parts = [_exact(perm, nd, rules, cache, opp, swap_probe) for nd in npc_decks]
        r = DeckResult(tuple(perm), min(p.first for p in parts),
                       min(p.second for p in parts), exact=_exact_tag(rules))
        best = r if best is None else _pick_best((best, r))
    return best


def _rank(results):
    return sorted(results, key=lambda r: (r.worst, r.avg), reverse=True)


# --- parallel screening / solving ------------------------------------------
#
# The screen/solve of one deck is independent of every other, so the two heavy
# passes fan out over a process pool.  Workers run at idle priority (os.nice 19)
# so a run never competes with a foreground game for CPU.  Jobs are cache-less
# (a shared dict can't cross processes; cross-deck reuse was marginal anyway).

def _nice_init():                       # pragma: no cover - runs in a subprocess
    try:
        if hasattr(os, "nice"):
            os.nice(19)
    except OSError:
        pass


def _resolve_workers(workers: int) -> int:
    if workers and workers > 0:
        return workers
    if workers < 0:
        return 1
    return max(1, (os.cpu_count() or 2) // 2)   # 0 -> half the logical CPUs


def _make_pool(nw: int):
    """A forked process pool at idle priority, or None if forking isn't available."""
    try:
        ctx = multiprocessing.get_context("fork")
    except ValueError:
        return None                              # no fork start method (e.g. Windows)
    try:
        return ProcessPoolExecutor(max_workers=nw, mp_context=ctx,
                                   initializer=_nice_init)
    except (OSError, ValueError):
        return None


def _screen_any_nc(deck, npc_decks, rules, tail, opp, swap_probe=0) -> DeckResult:
    deck = _screen_order(deck, npc_decks, rules)
    fs, ss = [], []
    for nd in npc_decks:
        a, b = _avg_sides(deck, nd, rules,
                          lambda st: screen_value(st, tail, opp), swap_probe)
        fs.append(a)
        ss.append(b)
    return DeckResult(tuple(deck), min(fs), min(ss), exact=False)


def _exact_any_nc(deck, npc_decks, rules, opp, order_keep=ORDER_PROBE,
                  swap_probe=0) -> DeckResult:
    best = None
    for perm in _probe_orders(deck, npc_decks, rules, order_keep):
        fs, ss = [], []
        for nd in npc_decks:
            a, b = _avg_sides(perm, nd, rules,
                              lambda st: _exact_value(st, rules, opp), swap_probe)
            fs.append(a)
            ss.append(b)
        r = DeckResult(tuple(perm), min(fs), min(ss), exact=_exact_tag(rules))
        best = r if best is None else _pick_best((best, r))
    return best


def _screen_job(job):                    # (deck, npc_decks, rules, tail, opp, swap_probe)
    return _screen_any_nc(*job)


def _exact_job(job):             # (deck, npc_decks, rules, opp, order_keep, swap_probe)
    return _exact_any_nc(*job)


def _imap(ex, fn, jobs):
    """fn over jobs, in order, lazily - on the pool if there is one."""
    if not jobs:
        return iter(())
    if ex is None:
        return map(fn, jobs)
    cs = max(1, len(jobs) // (ex._max_workers * 4))
    return ex.map(fn, jobs, chunksize=cs)


def recommend(npc_deck, rules: RuleSet, pool: list[int], *,
              shortlist_n: int = 16, exact_k: int = 25, top: int = 5,
              screen_tail: int = 6, opp: str = "optimal", swaps: bool = True,
              cand_cap: int = 0, worstcase_n: int = 0, workers: int = 0,
              order_probe: int = ORDER_PROBE, swap_probe: int = SWAP_PROBE,
              progress=None) -> Recommendation:
    """``npc_deck`` is the NPC's 5 card ids, or - when their deck is only known up
    to a random draw - a list of the possible 5-card decks; decks are then scored
    by their worst case across all of them.

    The search is a funnel: cap the candidate field by a cheap card heuristic
    (``cand_cap``, 0 = no cap); coarse-screen the whole field against one
    representative NPC draw; re-score the best ``worstcase_n`` against *every*
    possible draw (worst case); then exact-solve the top ``exact_k``.  For a
    fixed-deck NPC the middle step is a no-op.

    ``workers``: 0 = auto (half the logical CPUs, at idle priority), 1 = serial,
    N = that many worker processes.

    Under the **Order** rule the hand plays left-to-right, so each deck's
    arrangement matters: screening scores the greedy-best order, then the exact
    pass solves the ``order_probe`` most promising orderings of each finalist and
    keeps the winner - ``result.cards`` is the sequence to set in-game.

    Under the **Swap** rule one random card of yours is exchanged with one of
    theirs before play, so the deck you pick is never the hand you play.  Decks
    are scored across the 25 possible exchanges, **averaged** - the swap is
    random and uncontrollable, so its expectation is the honest number, unlike
    their deck draw which is still worst-cased.  ``swap_probe`` samples only the
    coarse screen (0 = all 25); every later phase re-scores on all 25, because
    picking the best of many truncated averages biases the winner optimistic.
    Margins for a Swap NPC are expected values, not guarantees.

    Under the **Chaos** rule you do not choose which card you play, so every ply
    is an expectimax node and no position can be solved to a full board in
    reasonable time.  The exact pass therefore runs a deeper screen instead (see
    CHAOS_TAIL) and every result comes back with ``exact=False``; the numbers are
    good estimates, not solved values.

    ``progress``, if given, is called with dict events (each carries ``msg``):
    ``{"phase":"screen","done","total"}`` through the coarse pass, then
    ``{"phase":"worstcase","done","total"}`` per re-scored deck, one
    ``{"phase":"exact-start","screened","k"}``, then
    ``{"phase":"exact"|"exact-worstcase","done","total","first","second"}`` per
    exact solve."""
    if len(pool) < 5:
        raise ValueError("need at least 5 cards in the pool")
    npc_decks = _normalize_npc_decks(npc_deck)
    multi = len(npc_decks) > 1
    pool = list(dict.fromkeys(pool))
    sl = pool if len(pool) <= 12 else shortlist(pool, rules, shortlist_n)
    cands = list(legal_decks(sl))
    if not cands:
        raise ValueError("no legal decks from the shortlist (high-rarity limit?)")
    if cand_cap and len(cands) > cand_cap:
        cands.sort(key=lambda d: sum(card_score(CARDS[i], rules) for i in d), reverse=True)
        cands = cands[:cand_cap]

    cache: dict = {}                          # only for the swap analysis below
    reps = tuple([_hardest_npc_deck(npc_decks, rules)] if multi else npc_decks)
    npc_t = tuple(npc_decks)

    nw = _resolve_workers(workers)
    # else the pool's startup outweighs the work.  Swap always qualifies: it costs
    # ~25 evaluations per candidate where every other rule costs one.
    big = len(cands) >= 500 or exact_k >= 6 or rules.swap
    ex = _make_pool(nw) if nw > 1 and big else None
    try:
        # phase 1: coarse-screen the whole field against the representative draw
        total = len(cands)
        step = max(1, total // 100)
        jobs = [(d, reps, rules, screen_tail, opp, swap_probe) for d in cands]
        coarse = []
        for i, res in enumerate(_imap(ex, _screen_job, jobs), 1):
            coarse.append(res)
            if progress and (i % step == 0 or i == total):
                progress({"phase": "screen", "done": i, "total": total,
                          "msg": f"screening {i}/{total} decks"})
        coarse = _rank(coarse)

        # phase 2: re-score the best survivors against every possible NPC draw
        if multi:
            wc_n = min(worstcase_n or max(top * 4, exact_k * 3, 24), len(coarse))
            jobs = [(dr.cards, npc_t, rules, screen_tail, opp, 0)
                    for dr in coarse[:wc_n]]
            rescored = []
            for i, res in enumerate(_imap(ex, _screen_job, jobs), 1):
                rescored.append(res)
                if progress:
                    progress({"phase": "worstcase", "done": i, "total": wc_n,
                              "msg": f"worst-case check {i}/{wc_n} vs all {len(npc_decks)} draws"})
            screened = _rank(rescored)
        else:
            screened = coarse

        k = min(exact_k, len(screened))
        if progress:
            vs = f"{len(npc_decks)} possible npc decks" if multi else "npc deck"
            progress({"phase": "exact-start", "screened": len(cands), "k": k,
                      "msg": (f"screened {len(cands)} decks vs {vs} (tail {screen_tail}, "
                              f"opp {opp}); exact-solving top {k}")})

        # phase 3: exact solves.  For a variable-deck NPC, rank the top k against
        # the representative draw first, then pay the full every-draw cost on only
        # the final `top`.
        okeep = order_probe if rules.order else 1
        exact = []
        if k and multi:
            jobs = [(dr.cards, reps[:1], rules, opp, okeep, 0)
                    for dr in screened[:k]]
            rep_ranked = []
            for n, res in enumerate(_imap(ex, _exact_job, jobs), 1):
                rep_ranked.append(res)
                if progress:
                    progress({"phase": "exact", "done": n, "total": k,
                              "first": res.first, "second": res.second,
                              "msg": (f"[{n}/{k}] {', '.join(res.names())}  "
                                      f"first {res.first:+g} second {res.second:+g}")})
            final = _rank(rep_ranked)[:min(top, k)]
            jobs = [(dr.cards, npc_t, rules, opp, okeep, 0) for dr in final]
            for n, res in enumerate(_imap(ex, _exact_job, jobs), 1):
                exact.append(res)
                if progress:
                    progress({"phase": "exact-worstcase", "done": n, "total": len(final),
                              "first": res.first, "second": res.second,
                              "msg": (f"[{n}/{len(final)}] {', '.join(res.names())}  "
                                      f"first {res.first:+g} second {res.second:+g}")})
        elif k:
            jobs = [(dr.cards, npc_t, rules, opp, okeep, 0)
                    for dr in screened[:k]]
            for n, res in enumerate(_imap(ex, _exact_job, jobs), 1):
                exact.append(res)
                if progress:
                    progress({"phase": "exact", "done": n, "total": k,
                              "first": res.first, "second": res.second,
                              "msg": (f"[{n}/{k}] {', '.join(res.names())}  "
                                      f"first {res.first:+g} second {res.second:+g}")})
    finally:
        if ex is not None:
            # wait=True, not False: cancel_futures already drops everything still
            # queued, so this only joins the jobs actually in flight - bounded by
            # one job.  With wait=False the executor's manager thread and its
            # forked workers outlive the call, and the interpreter's atexit hook
            # then blocks joining them: a process that calls recommend() a few
            # times prints its results and never exits.  That is the long-lived
            # GUI server, which calls this on every Recommend / refine click.
            ex.shutdown(wait=True, cancel_futures=True)

    # trust the exact slice; only fall back to estimates if nothing was solved
    ranked = _rank(exact) if exact else _rank(screened)
    rec = Recommendation(npc="", rules=rules, npc_deck=npc_decks[0],
                         screened=len(cands), results=ranked[:top])
    if swaps:
        rec.swaps = _swap_analysis(rec.best, pool, npc_decks, rules, cache,
                                   verify=exact_k > 0, tail=screen_tail, opp=opp,
                                   swap_probe=0)
    return rec


def _swap_analysis(base: DeckResult, pool, npc_decks, rules, cache,
                   verify=True, tail=6, opp="optimal", swap_probe=SWAP_PROBE):
    """For each slot in the recommended deck, the single best replacement from the
    pool, as (slot, out_name, in_name, margin_delta).  Candidates are picked by
    the greedy screen; when ``verify`` the winner is re-checked with an exact solve.

    Note the name clash: this is *deck editing* advice (swap a card of yours for a
    better one you own), nothing to do with the in-game **Swap rule** - that is
    handled by _matchups / _avg_sides and reaches here only as ``swap_probe``.
    """
    out = []
    base_worst = base.worst
    for slot in range(5):
        rest = [c for j, c in enumerate(base.cards) if j != slot]
        best = None
        for cand in pool:
            if cand in rest or cand == base.cards[slot]:
                continue
            deck = tuple(rest) + (cand,)
            if sum(CARDS[i].stars >= HIGH_RARITY for i in deck) > MAX_HIGH_PER_DECK:
                continue
            sc = _screen_any(deck, npc_decks, rules, cache, tail, opp)
            if best is None or sc.worst > best[1]:
                best = (cand, sc.worst)
        if best is None:
            continue
        res = (_exact_any((*rest, best[0]), npc_decks, rules, cache, opp) if verify
               else _screen_any((*rest, best[0]), npc_decks, rules, cache, tail, opp))
        if res.worst > base_worst:
            out.append((slot, CARDS[base.cards[slot]].name, CARDS[best[0]].name,
                        res.worst - base_worst))
    return sorted(out, key=lambda t: t[3], reverse=True)
