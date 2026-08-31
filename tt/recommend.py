"""Deck recommender.

A full solve per candidate deck is far too slow (thousands of ~20 s opening
solves), so this works in two passes:

1. **screen** every constraint-legal 5-card deck from a heuristic shortlist with a
   fast 1-ply greedy playout (both coin-toss orientations);
2. **exact-solve** the top slice with the real alpha-beta solver.

Decks are ranked by the worst of the two coin-toss outcomes, then by the average
margin.  The margin is always from your perspective (positive = you win).
"""
from __future__ import annotations

import multiprocessing
import os
import warnings
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from itertools import combinations

# Workers are forked: they inherit the loaded card dataset (and any test cards),
# start instantly, and never re-import __main__ - which keeps this working when
# the caller is a threaded HTTP server, a runpy'd script, or a heredoc.  They do
# pure arithmetic on read-only data straight after the fork, so the multi-thread
# fork warning does not apply here.
warnings.filterwarnings("ignore", message=r".*multi-threaded.*fork\(\).*",
                        category=DeprecationWarning)

from .data import CARDS, Card
from .model import EMPTY_BOARD, GameState, RuleSet, is_terminal, value_a
from .solver import analyze, apply, legal_moves, solve

HIGH_RARITY = 4          # cards at >= this many stars are deck-limited
MAX_HIGH_PER_DECK = 1    # VERIFY: standard decks allow one 4/5-star card


# --- heuristic card score (only used to pick the shortlist) ----------------

def card_score(c: Card, rules: RuleSet) -> float:
    s = c.sides
    total = sum(s)
    low_is_good = rules.reverse or rules.fallen_ace
    adj = (s[0] + s[1], s[1] + s[2], s[2] + s[3], s[3] + s[0])  # corner pairs
    if low_is_good:
        base = 44 - total + 0.5 * (20 - min(adj))
        if rules.fallen_ace:
            base += 3 * sum(v == 1 for v in s) - 2 * sum(v == 10 for v in s)
    else:
        base = total + 1.5 * sum(v == 10 for v in s) + 0.5 * max(adj)
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

def _board_margin(state: GameState) -> int:
    a = sum(1 for s in state.board if s is not None and s[1] == 0)
    b = sum(1 for s in state.board if s is not None and s[1] == 1)
    return a - b


def _greedy_step(state: GameState) -> GameState:
    """Apply the move that most improves the mover's board margin (1-ply, myopic)."""
    want_max = state.to_move == 0
    best_m, best_v = None, None
    for m in legal_moves(state):
        v = _board_margin(apply(state, *m))
        v = v if want_max else -v
        if best_v is None or v > best_v:
            best_v, best_m = v, m
    return apply(state, *best_m) if best_m is not None else state


def greedy_playout(state: GameState) -> int:
    s = state
    while not is_terminal(s) and legal_moves(s):
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
    while (not is_terminal(s) and legal_moves(s)
           and sum(1 for x in s.board if x is not None) < limit):
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
    swaps: list = field(default_factory=list)   # (slot, out_name, in_name, delta)

    @property
    def best(self) -> DeckResult:
        return self.results[0]


# --- orchestration -----------------------------------------------------

def _key(deck, npc_deck, side):
    return (tuple(sorted(deck)), tuple(sorted(npc_deck)), side)


def _states(deck, npc_deck, rules):
    hands = (tuple(deck), tuple(npc_deck))
    return (GameState(EMPTY_BOARD, hands, 0, rules),
            GameState(EMPTY_BOARD, hands, 1, rules))


def _screen(deck, npc_deck, rules, cache, tail=6, opp="optimal"):
    out = []
    for side, st in zip((0, 1), _states(deck, npc_deck, rules)):
        k = (tail, opp, *_key(deck, npc_deck, side))
        if k not in cache:
            cache[k] = screen_value(st, tail, opp)
        out.append(cache[k])
    return DeckResult(tuple(deck), out[0], out[1], exact=False)


def _exact(deck, npc_deck, rules, cache, opp="optimal"):
    vals = []
    for side, st in zip((0, 1), _states(deck, npc_deck, rules)):
        k = ("x", opp, *_key(deck, npc_deck, side))
        if k not in cache:
            try:
                cache[k] = analyze(st, opp=opp).best.value
            except ValueError:                       # Chaos / Roulette
                cache[k] = greedy_playout(st)
        vals.append(cache[k])
    return DeckResult(tuple(deck), vals[0], vals[1], exact=True)


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
    Reverse / Fallen Ace where low sides win."""
    low = rules.reverse or rules.fallen_ace
    def strength(nd):
        t = sum(sum(CARDS[c].sides) for c in nd)
        return -t if low else t
    return max(npc_decks, key=strength)


def _screen_any(deck, npc_decks, rules, cache, tail=6, opp="optimal"):
    """Screen ``deck`` against every possible NPC deck; keep the worst side-margins."""
    parts = [_screen(deck, nd, rules, cache, tail, opp) for nd in npc_decks]
    return DeckResult(tuple(deck), min(p.first for p in parts),
                      min(p.second for p in parts), exact=False)


def _exact_any(deck, npc_decks, rules, cache, opp="optimal"):
    parts = [_exact(deck, nd, rules, cache, opp) for nd in npc_decks]
    return DeckResult(tuple(deck), min(p.first for p in parts),
                      min(p.second for p in parts), exact=True)


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


def _screen_any_nc(deck, npc_decks, rules, tail, opp) -> DeckResult:
    fs, ss = [], []
    for nd in npc_decks:
        a, b = (screen_value(st, tail, opp) for st in _states(deck, nd, rules))
        fs.append(a)
        ss.append(b)
    return DeckResult(tuple(deck), min(fs), min(ss), exact=False)


def _exact_any_nc(deck, npc_decks, rules, opp) -> DeckResult:
    fs, ss = [], []
    for nd in npc_decks:
        vv = []
        for st in _states(deck, nd, rules):
            try:
                vv.append(analyze(st, opp=opp).best.value)
            except ValueError:                   # Chaos / Roulette
                vv.append(greedy_playout(st))
        fs.append(vv[0])
        ss.append(vv[1])
    return DeckResult(tuple(deck), min(fs), min(ss), exact=True)


def _screen_job(job):                            # (deck, npc_decks, rules, tail, opp)
    return _screen_any_nc(*job)


def _exact_job(job):                             # (deck, npc_decks, rules, opp)
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
    big = len(cands) >= 500 or exact_k >= 6   # else the pool's startup outweighs the work
    ex = _make_pool(nw) if nw > 1 and big else None
    try:
        # phase 1: coarse-screen the whole field against the representative draw
        total = len(cands)
        step = max(1, total // 100)
        jobs = [(d, reps, rules, screen_tail, opp) for d in cands]
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
            jobs = [(dr.cards, npc_t, rules, screen_tail, opp) for dr in coarse[:wc_n]]
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
        exact = []
        if k and multi:
            jobs = [(dr.cards, reps[:1], rules, opp) for dr in screened[:k]]
            rep_ranked = []
            for n, res in enumerate(_imap(ex, _exact_job, jobs), 1):
                rep_ranked.append(res)
                if progress:
                    progress({"phase": "exact", "done": n, "total": k,
                              "first": res.first, "second": res.second,
                              "msg": (f"[{n}/{k}] {', '.join(res.names())}  "
                                      f"first {res.first:+g} second {res.second:+g}")})
            final = _rank(rep_ranked)[:min(top, k)]
            jobs = [(dr.cards, npc_t, rules, opp) for dr in final]
            for n, res in enumerate(_imap(ex, _exact_job, jobs), 1):
                exact.append(res)
                if progress:
                    progress({"phase": "exact-worstcase", "done": n, "total": len(final),
                              "first": res.first, "second": res.second,
                              "msg": (f"[{n}/{len(final)}] {', '.join(res.names())}  "
                                      f"first {res.first:+g} second {res.second:+g}")})
        elif k:
            jobs = [(dr.cards, npc_t, rules, opp) for dr in screened[:k]]
            for n, res in enumerate(_imap(ex, _exact_job, jobs), 1):
                exact.append(res)
                if progress:
                    progress({"phase": "exact", "done": n, "total": k,
                              "first": res.first, "second": res.second,
                              "msg": (f"[{n}/{k}] {', '.join(res.names())}  "
                                      f"first {res.first:+g} second {res.second:+g}")})
    finally:
        if ex is not None:
            ex.shutdown(wait=False, cancel_futures=True)

    # trust the exact slice; only fall back to estimates if nothing was solved
    ranked = _rank(exact) if exact else _rank(screened)
    rec = Recommendation(npc="", rules=rules, npc_deck=npc_decks[0],
                         screened=len(cands), results=ranked[:top])
    if swaps:
        rec.swaps = _swap_analysis(rec.best, pool, npc_decks, rules, cache,
                                   verify=exact_k > 0, tail=screen_tail, opp=opp)
    return rec


def _swap_analysis(base: DeckResult, pool, npc_decks, rules, cache,
                   verify=True, tail=6, opp="optimal"):
    """For each slot in the recommended deck, the single best replacement from the
    pool, as (slot, out_name, in_name, margin_delta).  Candidates are picked by
    the greedy screen; when ``verify`` the winner is re-checked with an exact solve.
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
