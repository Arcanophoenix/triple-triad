#!/usr/bin/env python3
"""Pull NPC decks + rules from saved wiki NPC pages into data/decks.json.

Save an NPC's page (e.g. https://ffxiv.consolegameswiki.com/wiki/Triple_Triad_Master)
as "Web Page, Complete" into reference/NPCs/, then:

  scripts/scrape_npc.py                     # every page in reference/NPCs/
  scripts/scrape_npc.py "Triple Triad Master"

Scraped card lists overwrite whatever was in decks.json for that NPC; any 'notes'
you added are kept.  Rules are cross-checked against data/npcs.json.

NPCs with a fixed five are stored as {"cards": [...]}.  NPCs that draw a random
subset (some cards marked "Guaranteed in deck", the rest a pool) are stored as
{"fixed": [...], "pool": [...], "draw": N}.
"""
from __future__ import annotations

import argparse
import html
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tt.data import find_npc, load_decks, load_npcs, resolve, save_decks  # noqa: E402

NPC_DIR = pathlib.Path(__file__).resolve().parents[1] / "reference" / "NPCs"


def _text(frag: str) -> str:
    frag = re.sub(r"<[^>]+>", " ", frag)
    return re.sub(r"\s+", " ", html.unescape(frag)).strip()


# Wiki pages that state the wrong MATCH rules - key is the NPC name, value is the
# Match Rules row of the in-game Match Registration screen (regional rules are
# tracked separately in tt/regions.py, not here).  Applied over the scraped value
# so a re-scrape keeps the correction.
_RULE_OVERRIDES = {
    "Ourdilic": ["Order"],   # wiki says "All Open, Swap, Order"; the game's Match
                             # Rules row is just Order (confirmed 2026-08-31)
}


def parse_page(path: pathlib.Path) -> dict:
    s = path.read_text(encoding="utf-8", errors="replace")
    name = path.name.split(" - Final Fantasy XIV")[0].strip()

    # --- rules: from the infobox ---
    i = s.find(">Rules")
    if i < 0:
        i = s.find("Rules")
    flat = _text(s[max(0, i - 300): s.find("</table>", i) + 8 if i >= 0 else i])
    mr = re.search(r"Rules\s*:\s*([A-Za-z ,]+?)\s*(?:Cost|Requirement|Deck)", flat)
    rules = [r.strip() for r in mr.group(1).split(",")] if mr else []
    if name in _RULE_OVERRIDES:
        rules = list(_RULE_OVERRIDES[name])

    # --- deck: the "Deck" section table.  Each card row may carry a
    #     "Guaranteed in deck" marker; unmarked rows are the random pool that
    #     the game draws from to fill the deck to five. ---
    a = s.find('id="Deck"')
    b = s.find('id="Rewards"', a) if a >= 0 else -1
    sec = s[a:b] if a >= 0 else ""
    anchors = [(m.start(), html.unescape(m.group(1)))
               for m in re.finditer(r'title="([^"]+ Card)"', sec)]
    fixed, pool = [], []
    for j, (pos, cname) in enumerate(anchors):
        end = anchors[j + 1][0] if j + 1 < len(anchors) else len(sec)
        bucket = fixed if "Guaranteed in deck" in sec[pos:end] else pool
        if cname not in bucket:
            bucket.append(cname)
    pool = [c for c in pool if c not in fixed]

    if not anchors:  # fall back to the old infobox alt-scan
        box = s[max(0, i - 300): s.find("</table>", i) + 8 if i >= 0 else i]
        dpos = box.find("Deck")
        for cname in re.findall(r'alt="([^"]+ Card)"', box[dpos:] if dpos >= 0 else box):
            cname = html.unescape(cname)
            if cname not in fixed and len(fixed) < 5:
                fixed.append(cname)

    return {"name": name, "rules": rules, "fixed": fixed, "pool": pool, "file": path.name}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("npc", nargs="?", help="scrape just the page whose name contains this")
    args = p.parse_args(argv)

    if not NPC_DIR.is_dir():
        print(f"no {NPC_DIR} - save NPC wiki pages there first", file=sys.stderr)
        return 1
    pages = sorted(NPC_DIR.glob("*.html"))
    if args.npc:
        pages = [q for q in pages if args.npc.lower() in q.name.lower()]
    if not pages:
        print("no matching pages", file=sys.stderr)
        return 1

    roster = load_npcs()
    decks = load_decks()
    changed = 0
    for path in pages:
        info = parse_page(path)
        try:
            fixed = [resolve(c).name for c in info["fixed"]]
            pool = [resolve(c).name for c in info["pool"]]
        except KeyError as e:
            print(f"! {info['name']}: {e}", file=sys.stderr)
            continue

        total = len(fixed) + len(pool)
        if len(fixed) == 5 and not pool:
            deck_entry = {"cards": fixed}
            shown = ", ".join(fixed)
        elif 0 < len(fixed) < 5 <= total:
            draw = 5 - len(fixed)
            deck_entry = {"fixed": fixed, "pool": pool, "draw": draw}
            shown = f"{', '.join(fixed)}  +{draw} of [{', '.join(pool)}]"
        else:
            print(f"! {info['name']}: unexpected deck table - {len(fixed)} guaranteed "
                  f"/ {len(pool)} pool (want 5 guaranteed, or <5 with a pool of >={5 - len(fixed)})",
                  file=sys.stderr)
            continue

        canon = info["name"]
        try:
            rec = find_npc(info["name"], roster)
            canon = rec["name"]
            if rec["rules"] and sorted(rec["rules"]) != sorted(info["rules"]):
                print(f"  note: {canon} rules differ - page {info['rules']} vs "
                      f"roster {rec['rules']}")
        except KeyError:
            print(f"  note: {canon} not in data/npcs.json roster")

        prev = decks.get(canon, {})
        entry = dict(deck_entry)                       # deck fields first
        rules_out = info["rules"] or prev.get("rules")
        if rules_out:
            entry["rules"] = rules_out
        for k, v in prev.items():                      # keep notes etc.
            if k not in entry and k not in ("cards", "fixed", "pool", "draw", "rules"):
                entry[k] = v
        decks[canon] = entry
        changed += 1
        print(f"{canon}: {shown}   rules: {', '.join(info['rules']) or '(none)'}")

    if changed:
        save_decks(decks)
        print(f"\nwrote {changed} deck(s) to data/decks.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
