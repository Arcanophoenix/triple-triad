#!/usr/bin/env python3
"""Manage NPC decks that you enter by hand as you meet them in game.

  scripts/deck.py add "Aiglephine" Troll Ifrit Garuda "Ultros & Typhon" Ramuh
  scripts/deck.py add "Aiglephine" --rules "Three Open,Plus"   # override wiki rules
  scripts/deck.py show "Aiglephine"
  scripts/deck.py list

Card names are loose: case-insensitive, the word "Card" is optional, "&" or "and"
both work, and a bare number picks that main-series card.
"""
from __future__ import annotations

import argparse
import sys

from ttdata import Resolver, find_npc, load_decks, load_npcs, save_decks

DIRS = {"up": "↑", "right": "→", "down": "↓", "left": "←"}


def _fmt_sides(s: dict) -> str:
    def v(x):
        return "A" if x == 10 else str(x)
    return f"{v(s['up'])}/{v(s['right'])}/{v(s['down'])}/{v(s['left'])}"


def _print_deck(npc: dict, cards: list[dict], rules_override) -> None:
    rules = rules_override if rules_override is not None else npc["rules"]
    loc = npc["location"]
    print(f"{npc['name']}  —  {loc['zone']} ({loc['x']}, {loc['y']})")
    print(f"  rules : {', '.join(rules) or '(none)'}"
          + ("   [override]" if rules_override is not None else ""))
    print("  deck  :")
    for c in cards:
        star = "★" * c["stars"]
        typ = "" if c["type"] == "None" else f"  [{c['type']}]"
        print(f"    {c['name']:<34} {_fmt_sides(c['sides']):<12} {star}{typ}")


def cmd_add(args) -> int:
    npcs = load_npcs()
    try:
        npc = find_npc(npcs, args.npc)
    except KeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if len(args.cards) != 5:
        print(f"error: need exactly 5 cards, got {len(args.cards)}", file=sys.stderr)
        return 1
    r = Resolver()
    try:
        cards = [r.resolve(x) for x in args.cards]
    except KeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    decks = load_decks()
    entry = {"cards": [c["name"] for c in cards]}
    if args.rules is not None:
        entry["rules"] = [x.strip() for x in args.rules.split(",") if x.strip()]
    if args.notes:
        entry["notes"] = args.notes
    decks[npc["name"]] = entry
    save_decks(decks)

    print(f"saved deck for {npc['name']} ({len(decks)} NPC decks recorded)\n")
    _print_deck(npc, cards, entry.get("rules"))
    return 0


def cmd_show(args) -> int:
    npcs = load_npcs()
    decks = load_decks()
    try:
        npc = find_npc(npcs, args.npc)
    except KeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    entry = decks.get(npc["name"])
    if not entry:
        print(f"{npc['name']}: no deck recorded yet. Wiki rules: "
              f"{', '.join(npc['rules']) or '(none)'}")
        return 0
    r = Resolver()
    cards = [r.resolve(x) for x in entry["cards"]]
    _print_deck(npc, cards, entry.get("rules"))
    if entry.get("notes"):
        print(f"  notes : {entry['notes']}")
    return 0


def cmd_list(_args) -> int:
    decks = load_decks()
    if not decks:
        print("no NPC decks recorded yet")
        return 0
    for name in sorted(decks):
        print(f"  {name}")
    print(f"\n{len(decks)} recorded")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="record/replace an NPC's deck")
    a.add_argument("npc")
    a.add_argument("cards", nargs="*", help="5 card names")
    a.add_argument("--rules", default=None, help="comma-separated, overrides wiki rules")
    a.add_argument("--notes", default=None)
    a.set_defaults(fn=cmd_add)

    s = sub.add_parser("show", help="print an NPC's recorded deck + rules")
    s.add_argument("npc")
    s.set_defaults(fn=cmd_show)

    ls = sub.add_parser("list", help="list NPCs with recorded decks")
    ls.set_defaults(fn=cmd_list)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
