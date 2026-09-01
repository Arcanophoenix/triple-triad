#!/usr/bin/env python3
"""Recommend the best 5-card deck against an NPC from the cards you own.

  scripts/recommend.py "Arsieu"                 # uses that NPC's recorded deck + rules
  scripts/recommend.py "Arsieu" --pool all      # ignore ownership; theoretical best
  scripts/recommend.py "X" --npc-deck "a,b,c,d,e" --rules "Plus,Same"

Ranks decks by the worse of the two coin-toss outcomes (you-first / you-second)
under optimal play, then by average margin.  The heuristic shortlist is screened
with a fast greedy playout; the top slice is then solved exactly - tune the cost
with --shortlist and --exact.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tt.data import (  # noqa: E402
    CARDS, deck_draw, find_npc, is_variable_deck, load_collection, load_decks,
    npc_deck_options, resolve,
)
from tt.model import RuleSet  # noqa: E402
from tt.recommend import recommend  # noqa: E402
from tt.regions import (  # noqa: E402
    effective_rules, is_stale, region_for_npc, regional_rules,
)


def _ids(names):
    return [resolve(x.strip() if isinstance(x, str) else x).id for x in names]


def _npc_setup(args):
    npc = find_npc(args.npc)
    entry = load_decks().get(npc["name"], {})
    use_regional = not args.no_regional and not args.rules
    rnames = effective_rules(npc, deck_entry=entry, override=args.rules,
                             use_regional=use_regional)
    rules = RuleSet.from_names([r.strip() for r in rnames if r.strip()])

    if use_regional:
        region = region_for_npc(npc)
        reg, on = regional_rules(region)
        if reg:
            warn = "  (STALE - re-check in game)" if is_stale(on) else ""
            print(f"note: +regional rules for {region}: {', '.join(reg)} "
                  f"(recorded {on}){warn}")
        elif region and region != "(fixed rules)":
            print(f"note: no regional rules recorded for {region} - run "
                  f"`tt-cli regional {region!r} <rules>` or pass --rules")

    if args.npc_deck:
        return npc["name"], _ids(args.npc_deck.split(",")), rules
    if entry.get("cards"):
        return npc["name"], _ids(entry["cards"]), rules
    if is_variable_deck(entry):
        opts = npc_deck_options(entry)
        print(f"note: {npc['name']} draws {deck_draw(entry)} of "
              f"[{', '.join(entry['pool'])}] - scoring worst case across all "
              f"{len(opts)} possible decks (pass --npc-deck to pin one)")
        return npc["name"], [_ids(o) for o in opts], rules
    raise SystemExit(f"no deck recorded for {npc['name']!r}; pass --npc-deck "
                     f"or run: scripts/deck.py add {npc['name']!r} <5 cards>")


def _pool(kind: str) -> list[int]:
    if kind == "all":
        return [c.id for c in CARDS]
    owned = load_collection()["owned"]
    return [resolve(n).id for n in owned]


def _fmt(cards) -> str:
    return ", ".join(f"{CARDS[i].name} [{CARDS[i].high}]" for i in cards)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("npc")
    p.add_argument("--pool", choices=("owned", "all"), default="owned")
    p.add_argument("--npc-deck", default=None)
    p.add_argument("--rules", default=None,
                   help="override the full rule list (regional included), comma-separated")
    p.add_argument("--no-regional", action="store_true",
                   help="use the NPC's match rules only, skip the recorded regional rules")
    p.add_argument("--shortlist", type=int, default=16, help="top cards considered (default 16)")
    p.add_argument("--screen-tail", type=int, default=6,
                   help="plies solved exactly after a greedy opening, when screening (default 6)")
    p.add_argument("--exact", type=int, default=25, help="decks solved fully (default 25)")
    p.add_argument("--cand-cap", type=int, default=0,
                   help="cap the candidate field to the N best by card heuristic "
                        "(0 = no cap; bounds the screen regardless of pool size)")
    p.add_argument("--workers", type=int, default=0,
                   help="worker processes: 0 = auto (half your CPUs, idle priority), "
                        "1 = serial (default 0)")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--opp", choices=("optimal", "greedy"), default="optimal",
                   help="NPC model: optimal minimax (safe) or greedy (realistic vs the real NPC)")
    p.add_argument("--no-swaps", action="store_true", help="skip the upgrade analysis")
    p.add_argument("--swap-probe", type=int, default=None,
                   help="Swap rule: outcomes sampled in the coarse screen "
                        "(default 5, 0 = all 25); later phases always use all 25")
    args = p.parse_args(argv)

    try:
        name, npc_ids, rules = _npc_setup(args)
    except (KeyError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    pool = _pool(args.pool)

    multi = npc_ids and isinstance(npc_ids[0], list)
    print(f"target : {name}")
    print(f"rules  : {', '.join(rules.names()) or '(none)'}")
    if multi:
        print(f"npc    : {len(npc_ids)} possible decks, e.g. {_fmt(npc_ids[0])}")
    else:
        print(f"npc    : {_fmt(npc_ids)}")
    print(f"pool   : {len(pool)} cards ({args.pool})")
    if rules.roulette:
        fixed = [n for n in rules.names() if n != "Roulette"]
        if fixed:
            print(f"note   : Roulette rolls extra rules at match start - deck picked under "
                  f"the always-on rule(s) only ({', '.join(fixed)}); re-run with --rules "
                  f"once you see the roll for a match-specific pick")
        else:
            print("note   : Roulette NPC - the roll is unknown when you build the deck, so "
                  "this is the strongest deck under plain rules (a solid all-round pick)")
    if rules.swap:
        print("note   : Swap trades one random card of yours for one of theirs before "
              "play, so margins below are EXPECTED values over all 25 exchanges, not "
              "guarantees - any single match can land better or worse")
    t0 = time.time()

    def _progress(e):
        # keep the screening pass on one self-updating line; new line per phase
        end = "\r" if e.get("phase") == "screen" and e["done"] != e["total"] else "\n"
        print(f"  .. {e['msg']}      ", end=end, flush=True)

    rec = recommend(npc_ids, rules, pool, shortlist_n=args.shortlist,
                    exact_k=args.exact, top=args.top, screen_tail=args.screen_tail,
                    cand_cap=args.cand_cap, workers=args.workers, opp=args.opp,
                    swaps=not args.no_swaps, progress=_progress,
                    **({"swap_probe": args.swap_probe}
                       if args.swap_probe is not None else {}))

    print(f"\ndone in {time.time() - t0:.0f}s\n")
    print(f"{'deck':<4} {'first':>6} {'second':>7} {'worst':>6}  cards")
    for n, r in enumerate(rec.results, 1):
        tag = "" if r.exact else "  (est)"
        print(f"#{n:<3} {r.first:>+6g} {r.second:>+7g} {r.worst:>+6g}{tag}  {', '.join(r.names())}")

    b = rec.best
    verdict = "win" if b.worst > 0 else "draw" if b.worst == 0 else "loss"
    print(f"\nrecommended: {', '.join(b.names())}")
    if rules.order:
        seq = "  ".join(f"{n}.{CARDS[i].name}" for n, i in enumerate(b.cards, 1))
        print(f"  deck order   : {seq}")
        print("  (Order rule - set your in-game deck in exactly this left-to-right order)")
    print(f"  going first  : {b.first:+g}")
    print(f"  going second : {b.second:+g}   ->  worst case {verdict} by {abs(b.worst):g}")
    if rec.swaps:
        print("\nupgrades if you had them (exact):")
        for slot, out_n, in_n, delta in rec.swaps:
            print(f"  {out_n}  ->  {in_n}   worst case {delta:+g}")
    else:
        print("\nno single-card swap from the pool improves the worst case.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
