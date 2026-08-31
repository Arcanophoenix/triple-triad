#!/usr/bin/env python3
"""Extract Triple Triad card + NPC data from the saved FFXIV Console Games Wiki pages.

Inputs (saved "Web Page, Complete" HTML, kept in reference/):
  - "Triple Triad Cards - ... .html"   -> data/cards.json
  - "Triple Triad NPCs - ... .html"    -> data/npcs.json

The NPC list page has rules / location / rewards / MGP but NOT decklists;
those are entered by hand with scripts/deck.py as you meet each NPC.
"""
from __future__ import annotations
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _find(pattern: str) -> Path:
    for base in (ROOT / "reference", ROOT):
        hits = sorted(base.glob(pattern))
        if hits:
            return hits[0]
    raise SystemExit(f"no file matching {pattern!r} under reference/ or {ROOT}")


CARDS_HTML = _find("Triple Triad Cards*.html")
NPCS_HTML = _find("Triple Triad NPCs*.html")
OUT = ROOT / "data"

RARITY = {1: "Common", 2: "Uncommon", 3: "Rare", 4: "Epic", 5: "Legendary"}


def strip_tags(s: str) -> str:
    s = re.sub(r"<style[^>]*>.*?</style>", " ", s, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def row_cells(row: str) -> list[str]:
    return re.findall(r"<t[dh][^>]*?>(.*?)</t[dh]>", row, re.S)


def table_rows(page: str, table_marker: str) -> list[str]:
    start = page.find(table_marker)
    if start < 0:
        raise SystemExit(f"table not found: {table_marker!r}")
    end = page.find("</table>", start)
    body = page[start:end]
    return re.findall(r"<tr[^>]*>.*?</tr>", body, re.S)


def side_val(raw: str) -> int:
    t = strip_tags(raw)
    return 10 if t.upper() == "A" else int(t)


def first_link_slug(raw: str) -> str | None:
    m = re.search(r'/wiki/([^"#]+)"', raw)
    return m.group(1) if m else None


def parse_cards(page: str) -> list[dict]:
    rows = table_rows(page, '<table class="sortable item')
    out = []
    for r in rows:
        c = row_cells(r)
        if len(c) != 14 or "headerSort" in r:
            continue
        num = strip_tags(c[0])
        # main series is "1".."460"; the FF-crossover series is shown as "*1".."*15"
        series = "ff" if num.startswith("*") else "main"
        num = num.lstrip("*")
        if not num.isdigit():
            continue
        stars = c[3].count("\u2605")
        icon = None
        m = re.search(r'([^/"]+_card_icon1\.png)', c[1])
        if m:
            icon = html.unescape(m.group(1))   # src has &amp; etc.
        out.append(
            {
                "number": int(num),
                "series": series,
                "name": strip_tags(c[2]),
                "slug": first_link_slug(c[2]),
                "stars": stars,
                "rarity": RARITY.get(stars, "?"),
                "type": strip_tags(c[4]) or "None",
                "sides": {
                    "up": side_val(c[6]),
                    "right": side_val(c[7]),
                    "down": side_val(c[8]),
                    "left": side_val(c[9]),
                },
                "acquisition_type": strip_tags(c[11]),
                "acquired_by": strip_tags(c[12]),
                "patch": strip_tags(c[13]),
                "icon": icon,
            }
        )
    return out


LOC_RE = re.compile(r"^(?P<zone>.*?)\s*(?:\(X:\s*(?P<x>[\d.]+)\s*,\s*Y:\s*(?P<y>[\d.]+)\s*\))?\s*$")


def parse_npcs(page: str) -> list[dict]:
    rows = table_rows(page, '<table class="pve align-center sortable')
    out = []
    for r in rows:
        c = row_cells(r)
        if len(c) != 8 or "headerSort" in r:
            continue
        name = strip_tags(c[0])
        if not name:
            continue
        loc = strip_tags(c[1])
        lm = LOC_RE.match(loc)
        rules = [x.strip() for x in strip_tags(c[2]).split(",") if x.strip()]
        rewards = [x.strip() for x in strip_tags(c[5]).split(",") if x.strip()]
        cost = strip_tags(c[3])
        win = strip_tags(c[4])
        out.append(
            {
                "name": name,
                "slug": first_link_slug(c[0]),
                "location": {
                    "zone": lm.group("zone") if lm else loc,
                    "x": float(lm.group("x")) if lm and lm.group("x") else None,
                    "y": float(lm.group("y")) if lm and lm.group("y") else None,
                },
                "rules": rules,
                "mgp_cost": int(cost) if cost.isdigit() else None,
                "mgp_win": int(win) if win.isdigit() else None,
                "rewards": rewards,
                "unlock": strip_tags(c[6]),
                "patch": strip_tags(c[7]),
                "deck": None,  # filled by fetch_decks.py
            }
        )
    return out


def main() -> None:
    OUT.mkdir(exist_ok=True)
    cards = parse_cards(CARDS_HTML.read_text(encoding="utf-8", errors="replace"))
    npcs = parse_npcs(NPCS_HTML.read_text(encoding="utf-8", errors="replace"))

    (OUT / "cards.json").write_text(json.dumps(cards, indent=2, ensure_ascii=False))
    (OUT / "npcs.json").write_text(json.dumps(npcs, indent=2, ensure_ascii=False))

    print(f"cards: {len(cards)}  -> {OUT/'cards.json'}")
    print(f"npcs : {len(npcs)}  -> {OUT/'npcs.json'}")

    # sanity checks
    bad = [c for c in cards if not (1 <= c["stars"] <= 5)]
    if bad:
        print(f"WARN: {len(bad)} cards with odd star count", file=sys.stderr)
    for c in cards:
        for k, v in c["sides"].items():
            assert 1 <= v <= 10, (c["name"], k, v)
    nums = [c["number"] for c in cards if c["series"] == "main"]
    missing = sorted(set(range(1, max(nums) + 1)) - set(nums))
    if missing:
        print(f"WARN: gaps in main card numbers: {missing}", file=sys.stderr)
    print("series counts:", {s: sum(1 for c in cards if c["series"] == s) for s in {"main", "ff"}})
    types = sorted({c["type"] for c in cards})
    print("card types seen:", types)
    all_rules = sorted({x for n in npcs for x in n["rules"]})
    print("npc rules seen:", all_rules)


if __name__ == "__main__":
    main()
