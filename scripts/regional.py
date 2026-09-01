#!/usr/bin/env python3
"""Show or set the current Triple Triad regional rules.

  scripts/regional.py                          # list every region + what's recorded
  scripts/regional.py "The Black Shroud"       # just that region
  scripts/regional.py "The Black Shroud" Same Plus     # set it (today's date)
  scripts/regional.py "The Black Shroud" --clear       # forget it
  scripts/regional.py --npc Buscarron          # which region an NPC is in + its rules

Regional rules vary by area and reset daily at 15:00 UTC; read them off the
in-game Match Registration screen (the "Regional Rules" row).  The solver unions
them onto each NPC's match rules.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tt.data import find_npc  # noqa: E402
from tt.regions import (  # noqa: E402
    FIXED, REGIONS, clear_regional, is_stale, load_regional, region_for_npc,
    regional_rules, set_regional,
)


def _show(regions: list[str]) -> None:
    saved = load_regional()["regions"]
    width = max((len(r) for r in regions), default=0)
    for r in regions:
        ent = saved.get(r) or {}
        rules = ent.get("rules") or []
        if not rules:
            print(f"  {r:<{width}}  (not recorded)")
            continue
        when = ent.get("date") or "?"
        flag = "  STALE - re-check in game" if is_stale(ent.get("date")) else ""
        print(f"  {r:<{width}}  {', '.join(rules)}   [{when}]{flag}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("region", nargs="?", help="region name (partial match ok)")
    p.add_argument("rules", nargs="*", help="rule names to record for that region")
    p.add_argument("--clear", action="store_true", help="forget the region's rules")
    p.add_argument("--npc", help="print the region (and its rules) for this NPC")
    p.add_argument("--date", help="record under this ISO date instead of today")
    args = p.parse_args(argv)

    if args.npc:
        try:
            npc = find_npc(args.npc)
        except KeyError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        region = region_for_npc(npc)
        zone = (npc.get("location") or {}).get("zone", "?")
        if not region:
            print(f"{npc['name']} - {zone}: region not in the map (regional rules not applied)")
            return 0
        if region == FIXED:
            print(f"{npc['name']} - {zone}: ignores regional rules")
            return 0
        rr, on = regional_rules(region)
        extra = f"{', '.join(rr)}   [{on}]" if rr else "(not recorded)"
        print(f"{npc['name']} - {zone}  ->  region {region}:  {extra}")
        return 0

    if not args.region:
        _show(list(REGIONS))
        return 0

    matches = [r for r in REGIONS if args.region.lower() in r.lower()]
    if len(matches) != 1:
        opts = ", ".join(matches) if matches else ", ".join(REGIONS)
        print(f"error: {args.region!r} matched {len(matches)} regions ({opts})", file=sys.stderr)
        return 1
    region = matches[0]

    if args.clear:
        clear_regional(region)
        print(f"cleared regional rules for {region}")
        return 0
    if not args.rules:
        _show([region])
        return 0
    try:
        set_regional(region, args.rules, on=args.date)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    rr, on = regional_rules(region)
    print(f"{region}: {', '.join(rr)}   [{on}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
