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
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tt.data import find_npc  # noqa: E402
from tt.regions import (  # noqa: E402
    FIXED, MIN_CONSECUTIVE_PAIRS, MIN_DAYS_PER_REGION, REGIONS, by_region,
    clear_regional, cross_region_agreement, is_stale, load_history, load_regional,
    observations, region_for_npc, regional_rules, repeat_rate, rule_day,
    rule_frequency, seed_history, set_regional, weekday_counts,
)

_WD = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _todo() -> None:
    """What still needs reading off the Match Registration screen today."""
    today = rule_day().isoformat()
    obs = observations()
    done = sorted(r for (d, r) in obs if d == today)
    todo = [r for r in REGIONS if r not in done]
    print(f"rule-day {today}  (regionals roll at 15:00 UTC)")
    if done:
        for r in done:
            seen = obs[(today, r)]
            print(f"  logged   {r}: {', '.join(seen) if seen else 'no regional rules'}")
    if todo:
        print(f"  missing  {', '.join(todo)}")
    else:
        print("  every region logged for today")


def _history(limit: int) -> None:
    seed_history()
    rows = load_history()
    if not rows:
        print("no observations logged yet - record one with "
              "`tt-cli regional <region> <rules...>`")
        return
    for rec in rows[-limit:]:
        wd = _WD[date.fromisoformat(rec["day"]).weekday()]
        print(f"  {rec['day']}  {wd}  {rec['region']:<24} "
              f"{', '.join(rec['rules']) or '(none)'}")
    print(f"\n{len(rows)} observation(s) logged")


def _pattern() -> None:
    seed_history()
    obs = observations()
    if not obs:
        print("no observations logged yet - nothing to analyse")
        return
    days = sorted({d for d, _ in obs})
    regions = by_region(obs)
    print(f"{len(obs)} observation(s), {len(days)} rule-day(s) "
          f"({days[0]} to {days[-1]}), {len(regions)} region(s)\n")

    print("per-region rule frequency")
    for region, counts in sorted(rule_frequency(obs).items()):
        n = len(regions[region])
        seen = ", ".join(f"{r} x{c}" for r, c in counts.most_common())
        note = "" if n >= MIN_DAYS_PER_REGION else f"   (only {n} day(s) - not enough to read)"
        print(f"  {region:<24} {seen or '(none)'}{note}")

    same, total = repeat_rate(obs)
    print("\ndoes a region keep yesterday's rules?")
    if total < MIN_CONSECUTIVE_PAIRS:
        print(f"  {total} back-to-back day pair(s) so far - need "
              f"{MIN_CONSECUTIVE_PAIRS}+ before this means anything"
              + (f" (repeated {same} of {total})" if total else ""))
    else:
        print(f"  repeated {same}/{total} = {100 * same / total:.0f}% of the time")

    same, total = cross_region_agreement(obs)
    print("\ndo two regions roll the same rules on the same day?")
    if not total:
        print("  never logged two regions on one day - do that to test it")
    else:
        print(f"  matched {same}/{total} region pair(s) compared"
              + ("   (if this stays 0, each region rolls independently)"
                 if same == 0 else ""))

    wd = weekday_counts(obs)
    print("\nby weekday")
    for i in range(7):
        c = wd.get(i)
        if c:
            print(f"  {_WD[i]}  {', '.join(f'{r} x{n}' for r, n in c.most_common())}")
    thin = [r for r, rows in regions.items() if len(rows) < MIN_DAYS_PER_REGION]
    if thin:
        print(f"\nnote: {len(thin)} region(s) still under {MIN_DAYS_PER_REGION} "
              f"logged days. Frequencies above are indicative only - with a handful "
              f"of samples any ruleset can look 'favoured' by chance.")


def _show(regions: list[str]) -> None:
    saved = load_regional()["regions"]
    width = max((len(r) for r in regions), default=0)
    for r in regions:
        ent = saved.get(r)
        if ent is None:
            print(f"  {r:<{width}}  (not recorded)")
            continue
        # an empty list is a real reading - the screen said None/None - and must
        # not be shown as "not recorded", or a logged day looks like a missing one
        rules = ent.get("rules") or []
        what = ", ".join(rules) if rules else "no regional rules"
        when = ent.get("date") or "?"
        flag = "  STALE - re-check in game" if is_stale(ent.get("date")) else ""
        print(f"  {r:<{width}}  {what}   [{when}]{flag}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("region", nargs="?", help="region name (partial match ok)")
    p.add_argument("rules", nargs="*", help="rule names to record for that region")
    p.add_argument("--clear", action="store_true", help="forget the region's rules")
    p.add_argument("--none", dest="none", action="store_true",
                   help="record that the region has NO regional rules today "
                        "(the screen showed None/None) - different from not recorded")
    p.add_argument("--npc", help="print the region (and its rules) for this NPC")
    p.add_argument("--date", help="record under this rule-day instead of today "
                                  "(ISO; a rule-day runs 15:00 UTC to 15:00 UTC)")
    p.add_argument("--today", action="store_true",
                   help="what is still unlogged for the current rule-day")
    p.add_argument("--history", nargs="?", type=int, const=40, default=None,
                   metavar="N", help="the last N logged observations (default 40)")
    p.add_argument("--pattern", action="store_true",
                   help="look for a pattern in everything logged so far")
    args = p.parse_args(argv)

    if args.today:
        _todo()
        return 0
    if args.history is not None:
        _history(args.history)
        return 0
    if args.pattern:
        _pattern()
        return 0

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
    if not args.rules and not args.none:
        _show([region])
        return 0
    try:
        set_regional(region, [] if args.none else args.rules, on=args.date)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    rr, on = regional_rules(region)
    print(f"{region}: {', '.join(rr) if rr else 'no regional rules'}   [{on}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
