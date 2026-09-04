#!/usr/bin/env python3
"""Download official in-game card portraits into reference/card-art/.

  scripts/fetch_card_art.py                 # every card missing art
  scripts/fetch_card_art.py --only "Ifrit"
  scripts/fetch_card_art.py --limit 10 --dry-run
  scripts/fetch_card_art.py --force          # re-fetch even if present

Fetches straight from XIVAPI's public asset endpoint, no local game
install needed - it already serves the game's textures converted to PNG.
The icon id formula (LARGE_OFFSET + collect_id) and image path layout are
lifted from ffxivcollect.com's own card_images.rake (the site is MIT
licensed; see reference/ffxiv-collect*.zip). collect_id is the field this
project already hand-tagged 475/475 cards with via `tt-cli import`.

Saves reference/card-art/<card.id>.png, where <card.id> is this project's
own list-index id (what scripts/gui.py's /card/<id>.png route keys on) -
so a card with no collect_id yet just isn't fetchable, not mis-filed.
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tt import paths  # noqa: E402
from tt.data import CARDS  # noqa: E402

ASSET_URL = "https://v2.xivapi.com/api/asset"
LARGE_OFFSET = 87000
UA = "TripleTriadSolver/0.1 (personal deck tool; github.com search 'Triple Triad solver')"
OUT_DIR = paths.REFERENCE_DIR / "card-art"


def icon_path(collect_id: int) -> str:
    number = str(LARGE_OFFSET + collect_id).rjust(6, "0")
    directory = number[:3].ljust(6, "0")
    return f"ui/icon/{directory}/{number}_hr1.tex"


def asset_url(collect_id: int) -> str:
    query = urllib.parse.urlencode({"path": icon_path(collect_id), "format": "png"})
    return f"{ASSET_URL}?{query}"


def _get_bytes(url: str, tries: int = 3) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError):
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))
    raise RuntimeError("unreachable")


def _has_art(card_id: int) -> bool:
    f = OUT_DIR / f"{card_id}.png"
    return f.is_file() and f.stat().st_size > 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", action="append", default=[],
                   help="fetch just cards whose name contains this (repeatable)")
    p.add_argument("--limit", type=int, default=0, help="stop after N cards")
    p.add_argument("--force", action="store_true",
                   help="fetch even for cards that already have art on disk")
    p.add_argument("--delay", type=float, default=0.3, help="seconds between requests")
    p.add_argument("--dry-run", action="store_true", help="list what would be fetched")
    args = p.parse_args(argv)

    cards = [c for c in CARDS if c.collect_id]
    no_collect_id = [c for c in CARDS if not c.collect_id]
    if args.only:
        subs = [s.lower() for s in args.only]
        cards = [c for c in cards if any(s in c.name.lower() for s in subs)]

    todo = [c for c in cards if args.force or not _has_art(c.id)]
    if args.limit:
        todo = todo[: args.limit]
    have = sum(1 for c in cards if _has_art(c.id))
    print(f"{len(cards)} cards have a collect_id; {have} already have art; "
          f"{len(todo)} to fetch{' (dry run)' if args.dry_run else ''}")
    if no_collect_id:
        print(f"({len(no_collect_id)} card(s) have no collect_id, can't be fetched: "
              + ", ".join(c.name for c in no_collect_id[:10])
              + (", ..." if len(no_collect_id) > 10 else "") + ")")
    if args.dry_run:
        for c in todo:
            print(f"  {c.id:>3}  {c.name:32} {asset_url(c.collect_id)}")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    got = 0
    fail = []
    for i, c in enumerate(todo, 1):
        try:
            data = _get_bytes(asset_url(c.collect_id))
            (OUT_DIR / f"{c.id}.png").write_bytes(data)
            got += 1
            print(f"  [{i}/{len(todo)}] {c.name}: {len(data) // 1024} KB")
        except Exception as e:  # noqa: BLE001
            fail.append(c.name)
            print(f"  [{i}/{len(todo)}] ! {c.name}: {e}", file=sys.stderr)
        if i < len(todo):
            time.sleep(args.delay)

    print(f"\nsaved {got} card art file(s)"
          + (f"; {len(fail)} failed: {', '.join(fail)}" if fail else ""))
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
