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
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tt.data import (  # noqa: E402
    CARDS, is_variable_deck, load_collection, load_decks, load_npcs,
    npc_deck_options, resolve,
)
from tt.model import RuleSet  # noqa: E402
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


def solver_edge(npc: dict, decks: dict, pool: list[int]) -> float | None:
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
                        shortlist_n=14, cand_cap=300, screen_tail=4, exact_k=0,
                        workers=1)   # called once per NPC in a loop; pool startup would dominate
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
    args = p.parse_args(argv)

    npcs = load_npcs()
    decks = load_decks()
    if args.zone:
        z = args.zone.lower()
        npcs = [n for n in npcs if z in n["location"]["zone"].lower()]

    pool = ([c.id for c in CARDS] if args.pool == "all"
            else [resolve(x).id for x in load_collection()["owned"]])

    solve = not args.no_solve
    rows = []
    for n in npcs:
        s = score(n)
        e = solver_edge(n, decks, pool) if solve else None
        rows.append((s, tier(s), n, e))

    if args.challenge:
        rows = [r for r in rows if r[3] is not None and r[3] >= 0]
        rows.sort(key=lambda r: (-r[3], r[0]))
    else:
        rows.sort(key=lambda r: (r[0], r[2]["name"]), reverse=args.reverse)
    if args.limit:
        rows = rows[:args.limit]

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
