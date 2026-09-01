#!/usr/bin/env python3
"""Rank Triple Triad NPCs by rough difficulty - a guide to who to take on next.

  scripts/difficulty.py                 # every NPC, easiest first
  scripts/difficulty.py --reverse       # hardest first
  scripts/difficulty.py --zone "Gold Saucer"
  scripts/difficulty.py --challenge     # only NPCs you can currently beat (needs recorded decks)
  scripts/difficulty.py --no-solve      # skip the solver column (instant)

The game exposes no difficulty rating, so the score is a heuristic from the
NPC's MGP payout, reward-card rarity, patch, and ruleset.  When the NPC's deck
is recorded in data/decks.json the table also shows the solver's real verdict
against your collection - that column is the one to trust.
"""
from __future__ import annotations

import argparse
import multiprocessing
import os
import pathlib
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tt.data import (  # noqa: E402
    CARDS, is_variable_deck, load_collection, load_decks, load_npcs,
    npc_deck_options, resolve,
)
from tt.model import RuleSet  # noqa: E402
from tt.progress import (  # noqa: E402
    describe, is_reachable, load_progress, save_progress,
)
from tt.recommend import recommend  # noqa: E402

TIERS = [(15, "intro"), (32, "easy"), (52, "moderate"), (70, "hard"), (999, "brutal")]


def _patch_norm(p: str) -> float:
    try:
        v = float(str(p))                              # "4.45" -> 4.45, "7.5" -> 7.5
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, (v - 2.0) / 5.5))          # 2.0 -> 0, 7.5 -> 1


def _reward_star(npc: dict) -> int:
    best = 0
    for rw in npc.get("rewards") or []:
        try:
            best = max(best, resolve(rw).stars)
        except KeyError:
            pass
    return best                                         # 0 == couldn't resolve


def _rules_adj(rules) -> int:
    rs = set(rules or [])
    a = 0
    if rs & {"Chaos", "Roulette"}:
        a += 8                                          # can't guarantee a result
    if "Swap" in rs:
        a += 5
    if "Order" in rs:
        a += 4
    if {"Plus", "Same"} <= rs:
        a += 5
    elif rs & {"Plus", "Same"}:
        a += 3
    if rs & {"Reverse", "Fallen Ace"}:
        a += 4                                          # inverts card evaluation
    if rs & {"Ascension", "Descension"}:
        a += 2
    if "Sudden Death" in rs:
        a += 3
    if "All Open" in rs:
        a -= 6                                          # you see their whole hand
    if "Three Open" in rs:
        a -= 3
    return a


def score(npc: dict) -> float:
    mgp = min(npc.get("mgp_win") or 0, 120) / 120
    star = _reward_star(npc)
    reward = (star - 1) / 4 if star else 0.4            # unknown -> middling
    base = 100 * (0.38 * mgp + 0.30 * reward + 0.20 * _patch_norm(npc.get("patch")))
    return max(0.0, min(100.0, base + _rules_adj(npc.get("rules"))))


def tier(s: float) -> str:
    return next(name for cap, name in TIERS if s < cap)


def _ids(names):
    return [resolve(x).id for x in names]


# The cheap screen is not just noisy, it is biased LOW.  Measured against a
# config with a real exact slice over 13 NPCs spanning the roster: mean absolute
# error 4.00, max 6.00, and every single row understated - never once optimistic.
# So an NPC reading -4 here can genuinely be a winnable 0, and `--challenge`
# (which filters on >= 0) was hiding matchups the player can already take.
#
# Fixing it everywhere is not affordable: the accurate config costs ~8.6x, which
# is ~12 minutes across all 134 NPCs versus ~90 seconds.  But it only has to be
# right where the answer can flip, so `--challenge` re-checks the band where the
# bias could cross zero and leaves the rest on the cheap pass.
SCREEN = dict(shortlist_n=14, cand_cap=300, screen_tail=4, exact_k=0)
ACCURATE = dict(shortlist_n=14, cand_cap=300, screen_tail=6, exact_k=0)
_RECHECK_BAND = -6.0     # = the measured worst-case understatement
_RECHECK_CAP = 40        # most promising N; a full re-check is minutes even in parallel


def _nice_init():                        # pragma: no cover
    try:
        if hasattr(os, "nice"):
            os.nice(19)
    except OSError:
        pass


def borderline(rows, band: float = _RECHECK_BAND, cap: int = _RECHECK_CAP):
    """Rows worth re-scoring accurately, best-looking first.

    ``band`` is the measured worst-case understatement of the cheap screen, so a
    row at or above it could genuinely be >= 0 and must not be filtered out on
    the cheap number alone.  ``cap`` bounds the work: the accurate pass is ~5.6s
    per NPC, and without a cap the band can hold most of the roster (measured:
    17+ minutes serially).  Rows are ordered by the cheap value first so the cap
    keeps the most promising ones, which are the ones that can reach the list.
    """
    cand = [r for r in rows if r[3] is not None and r[3] >= band]
    cand.sort(key=lambda r: -r[3])
    return cand[:cap] if cap else cand


def _recheck_job(job):
    npc, decks, pool = job
    return npc["name"], solver_edge(npc, decks, pool, ACCURATE)


def _recheck(cands, decks, pool):
    """Re-score the borderline rows accurately, fanned out over NPCs.

    Parallel because the accurate config costs ~5.6s per NPC and the band can hold
    most of the roster - serially that is 15+ minutes, which nobody will wait for.
    Each NPC's own recommend() stays serial (workers=1): the pool lives out here,
    where there is real work per task, rather than being started and torn down
    once per NPC.
    """
    jobs = [(npc, decks, pool) for _s, _t, npc, _e in cands]
    nw = max(1, (os.cpu_count() or 2) // 2)
    ex = None
    if len(jobs) > 2 and nw > 1:
        try:
            ex = ProcessPoolExecutor(max_workers=nw,
                                     mp_context=multiprocessing.get_context("fork"),
                                     initializer=_nice_init)
        except (OSError, ValueError):
            ex = None
    try:
        out = dict(ex.map(_recheck_job, jobs) if ex else map(_recheck_job, jobs))
    finally:
        if ex is not None:
            ex.shutdown(wait=True, cancel_futures=True)
    return [(s_, t_, n_, out.get(n_["name"])) for s_, t_, n_, _e in cands]


def solver_edge(npc: dict, decks: dict, pool: list[int], cfg: dict | None = None) -> float | None:
    """Solver's worst-case margin for your best deck vs this NPC (None if no deck)."""
    entry = decks.get(npc["name"])
    if not entry or len(pool) < 5:
        return None
    rnames = entry.get("rules") or npc.get("rules") or []
    rules = RuleSet.from_names([r.strip() for r in rnames if r.strip()])
    try:
        if entry.get("cards"):
            npc_arg = _ids(entry["cards"])
        elif is_variable_deck(entry):
            npc_arg = [_ids(o) for o in npc_deck_options(entry)]
        else:
            return None
        rec = recommend(npc_arg, rules, pool, opp="greedy", top=1, swaps=False,
                        workers=1,   # called once per NPC in a loop; pool startup would dominate
                        **(cfg or SCREEN))
    except (ValueError, KeyError):
        return None
    return rec.best.worst


def _edge_txt(e: float | None) -> str:
    if e is None:
        return ""
    if e >= 6:
        return f"you win +{e:g}"
    if e >= 2:
        return f"you're ahead +{e:g}"
    if e >= -1:
        return f"coin-flip ({e:+g})"
    return f"you're behind {e:+g} - better cards needed"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pool", choices=("owned", "all"), default="owned",
                   help="card pool for the solver column (default: owned)")
    p.add_argument("--zone", help="only NPCs whose zone contains this text")
    p.add_argument("--reverse", action="store_true", help="hardest first")
    p.add_argument("--limit", type=int, default=0, help="show only the first N rows")
    p.add_argument("--no-solve", action="store_true", help="skip the solver column")
    p.add_argument("--challenge", action="store_true",
                   help="only NPCs you can beat now (recorded deck + solver >= 0), best matchup first")
    p.add_argument("--progress", metavar="PATCH|EXPANSION", default=None,
                   help="record how far through the story you are (e.g. 'ShB' or "
                        "'6.3') and hide NPCs added by later content; stored in "
                        "collection.json, so you only set it when it changes")
    p.add_argument("--fast", action="store_true",
                   help="skip the accurate re-check of borderline matchups in "
                        "--challenge (quicker, but understates by ~4 on average)")
    p.add_argument("--everywhere", action="store_true",
                   help="ignore the recorded story progress and list every NPC")
    args = p.parse_args(argv)

    if args.progress is not None:
        try:
            save_progress(args.progress)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    progress = None if args.everywhere else load_progress()

    npcs = load_npcs()
    decks = load_decks()
    if args.zone:
        z = args.zone.lower()
        npcs = [n for n in npcs if z in n["location"]["zone"].lower()]
    # An NPC behind story progress is not a suggestion, it is noise - you cannot
    # travel there.  Filtered before the solver runs, which also saves the work.
    gated = 0
    if progress is not None:
        keep = [n for n in npcs if is_reachable(n, progress)]
        gated = len(npcs) - len(keep)
        npcs = keep

    pool = ([c.id for c in CARDS] if args.pool == "all"
            else [resolve(x).id for x in load_collection()["owned"]])

    solve = not args.no_solve
    rows = []
    for n in npcs:
        s = score(n)
        e = solver_edge(n, decks, pool) if solve else None
        rows.append((s, tier(s), n, e))

    if args.challenge:
        # re-score the band where the cheap pass's low bias could hide a winnable
        # matchup, then filter - filtering first would discard exactly those
        cand = borderline(rows)
        if cand and not args.fast:
            print(f"re-checking {len(cand)} borderline matchup(s) accurately…",
                  file=sys.stderr, flush=True)
            cand = _recheck(cand, decks, pool)
        rows = [r for r in cand if r[3] is not None and r[3] >= 0]
        rows.sort(key=lambda r: (-r[3], r[0]))
    else:
        rows.sort(key=lambda r: (r[0], r[2]["name"]), reverse=args.reverse)
    if args.limit:
        rows = rows[:args.limit]

    if progress is not None:
        print(f"story progress: {describe(progress)}"
              + (f" - {gated} NPC(s) from later content hidden "
                 f"(--everywhere to show them)" if gated else ""))
    elif not args.everywhere:
        print("note: story progress not set, so NPCs you cannot reach yet are "
              "listed too - set it once with `--progress ShB` (or a patch number)")

    if not rows:
        print("no NPCs match" + (" (record some decks with scripts/scrape_npc.py"
                                 " for the challenge view)" if args.challenge else ""))
        return 0

    print(f"{'tier':9} {'score':>5}  {'NPC':30} {'zone':22} {'rules':22} {'rwd':4} "
          f"{'MGP':>4}" + ("  your best deck" if solve else ""))
    print("-" * (100 if solve else 84))
    for s, t, n, e in rows:
        star = _reward_star(n)
        print(f"{t:9} {s:5.0f}  {n['name'][:30]:30} {n['location']['zone'][:22]:22} "
              f"{(', '.join(n.get('rules') or []) or '-')[:22]:22} "
              f"{('*' + str(star)) if star else '?':4} {n.get('mgp_win') or 0:4}"
              + (f"  {_edge_txt(e)}" if solve else ""))

    if solve and not args.challenge:
        known = sum(1 for _s, _t, _n, e in rows if e is not None)
        print(f"\n{known}/{len(rows)} shown have a recorded deck; the rest are the "
              f"heuristic only. Add decks with `tt-cli scrape`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
