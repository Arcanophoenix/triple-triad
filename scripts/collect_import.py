#!/usr/bin/env python3
"""Import an FFXIV Collect account export: cards you own, NPCs you have beaten.

  scripts/collect_import.py export.json            # merge into your collection
  scripts/collect_import.py export.json --replace  # make the export authoritative
  scripts/collect_import.py export.json --dry-run  # show what would change
  scripts/collect_import.py --beaten               # list NPCs recorded as beaten

Get the file from ffxivcollect.com: sign in, open your character, Export.  The
download's name contains your character and world, so it is gitignored here.

Merging is the default because cards and wins are only ever gained - a union
cannot lose anything you ticked by hand, whereas a replace would drop cards the
export does not know about yet.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tt.collect import (  # noqa: E402
    apply_export, load_beaten, load_export, map_cards, map_npcs,
    unimportable_npcs,
)
from tt.data import load_npcs, read_collection  # noqa: E402


def _plural(n: int, one: str, many: str | None = None) -> str:
    return one if n == 1 else (many or one + "s")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("export", nargs="?", help="the exported .json file")
    p.add_argument("--replace", action="store_true",
                   help="overwrite your collection with the export instead of merging")
    p.add_argument("--dry-run", action="store_true",
                   help="report what would change and write nothing")
    p.add_argument("--beaten", action="store_true",
                   help="list the NPCs currently recorded as beaten")
    args = p.parse_args(argv)

    if args.beaten:
        beaten = load_beaten()
        total = len(load_npcs())
        print(f"{len(beaten)}/{total} NPC(s) recorded as beaten")
        for n in sorted(beaten):
            print(f"  {n}")
        return 0

    if not args.export:
        p.error("give an export file, or --beaten")

    try:
        data = load_export(args.export)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.dry_run:
        cards, bad_cards = map_cards(data.get("cards"))
        npcs, bad_npcs = map_npcs(data.get("npcs"))
        col = read_collection()
        have_c = set(col.get("owned") or [])
        have_n = set(col.get("npcs_beaten") or [])
        print(f"export holds {len(cards)} card(s) and {len(npcs)} beaten NPC(s)")
        print(f"would add {len(set(cards) - have_c)} card(s), "
              f"{len(set(npcs) - have_n)} NPC(s)")
        if args.replace:
            print(f"would REMOVE {len(have_c - set(cards))} card(s), "
                  f"{len(have_n - set(npcs))} NPC(s)")
        _warn(bad_cards, bad_npcs)
        return 0

    r = apply_export(data, replace=args.replace)
    print(f"cards : +{len(r['cards_added'])}"
          + (f"  -{len(r['cards_removed'])}" if r["cards_removed"] else "")
          + f"   now {r['cards_total']}")
    print(f"beaten: +{len(r['npcs_added'])}"
          + (f"  -{len(r['npcs_removed'])}" if r["npcs_removed"] else "")
          + f"   now {r['npcs_total']}/{len(load_npcs())}")
    for n in r["npcs_added"][:10]:
        print(f"  beat {n}")
    if len(r["npcs_added"]) > 10:
        print(f"  ... and {len(r['npcs_added']) - 10} more")
    _warn(r["unknown_card_ids"], r["unknown_npc_ids"])
    return 0


def _warn(bad_cards, bad_npcs) -> None:
    if bad_cards:
        print(f"\nnote: {len(bad_cards)} card id(s) in the export did not match a "
              f"card here: {bad_cards[:10]}{' ...' if len(bad_cards) > 10 else ''}\n"
              f"      Collect numbers the 460 main-series cards and leaves the 15 "
              f"FF-collab cards unnumbered, so those cannot be imported.")
    if bad_npcs:
        print(f"\nnote: {len(bad_npcs)} NPC id(s) in the export did not match: "
              f"{bad_npcs[:10]}{' ...' if len(bad_npcs) > 10 else ''}")
    missing = unimportable_npcs()
    if missing:
        print(f"\nnote: {', '.join(missing)} {_plural(len(missing), 'is', 'are')} "
              f"not on FFXIV Collect, so an import can never tick them "
              f"- mark by hand.")


if __name__ == "__main__":
    raise SystemExit(main())
