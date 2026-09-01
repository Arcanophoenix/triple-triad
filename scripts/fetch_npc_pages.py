#!/usr/bin/env python3
"""Download individual NPC wiki pages listed on the saved "Triple Triad NPCs" index.

  scripts/fetch_npc_pages.py                 # fetch every roster NPC not already saved
  scripts/fetch_npc_pages.py --only Buscarron --only Dominiac
  scripts/fetch_npc_pages.py --limit 10 --dry-run
  scripts/fetch_npc_pages.py --force         # re-fetch even if the file exists

Saves to reference/NPCs/<name> - Final Fantasy XIV Online Wiki - FFXIV _ FF14
Online Community Wiki and Guide.html, the layout scripts/scrape_npc.py expects.
Run `./tt-cli scrape` afterwards to import decks + rules into data/decks.json.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tt.data import load_npcs  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NPC_DIR = ROOT / "reference" / "NPCs"
SUFFIX = " - Final Fantasy XIV Online Wiki - FFXIV _ FF14 Online Community Wiki and Guide.html"
INDEX_GLOB = "Triple Triad NPCs*.html"
UA = "Mozilla/5.0 (X11; Linux x86_64) TripleTriadSolver/1.0 (personal deck-data scrape)"
_ROW = re.compile(
    r'<tr>\s*<td>\s*<a href="(https://ffxiv\.consolegameswiki\.com/wiki/[^"]+)"'
    r' title="([^"]+)"[^>]*>([^<]+)</a>'
)


def _index_path() -> Path:
    for base in (ROOT / "reference", ROOT):
        hits = sorted(base.glob(INDEX_GLOB))
        if hits:
            return hits[0]
    raise SystemExit(f"no {INDEX_GLOB!r} under reference/ - save the NPC list page first")


def _pairs(index_html: str, roster: set[str]) -> list[tuple[str, str]]:
    """(canonical roster name, wiki url) for every NPC row in the index table.

    The link text is the plain name; the title may be disambiguated
    ("Prudence (NPC)"), so match the roster on text first, then title, then
    title with any trailing "(...)" stripped.
    """
    seen, out = set(), []
    for m in _ROW.finditer(index_html):
        url = m.group(1)
        title = html.unescape(m.group(2))
        text = html.unescape(m.group(3)).strip()
        name = next((c for c in (text, title, re.sub(r"\s*\([^)]*\)$", "", title))
                     if c in roster), None)
        if name and name not in seen:
            seen.add(name)
            out.append((name, url))
    return out


def _dest(name: str) -> Path:
    return NPC_DIR / (name.replace("/", "-") + SUFFIX)


def _fetch(url: str, tries: int = 3) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError) as e:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))
    raise RuntimeError("unreachable")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", action="append", default=[],
                   help="fetch just NPCs whose name contains this (repeatable)")
    p.add_argument("--limit", type=int, default=0, help="stop after N fetches")
    p.add_argument("--force", action="store_true", help="re-fetch pages that already exist")
    p.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    p.add_argument("--dry-run", action="store_true", help="list what would be fetched")
    args = p.parse_args(argv)

    NPC_DIR.mkdir(parents=True, exist_ok=True)
    roster = {n["name"] for n in load_npcs()}
    pairs = _pairs(_index_path().read_text(encoding="utf-8", errors="replace"), roster)
    if not pairs:
        print("no NPC rows found in the index page", file=sys.stderr)
        return 1
    if args.only:
        subs = [s.lower() for s in args.only]
        pairs = [(n, u) for n, u in pairs if any(s in n.lower() for s in subs)]

    todo = [(n, u) for n, u in pairs if args.force or not _dest(n).is_file()]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(pairs)} NPCs in scope, {len(todo)} to fetch"
          f"{' (dry run)' if args.dry_run else ''}")
    if args.dry_run:
        for n, u in todo:
            print(f"  {n:32} {u}")
        return 0

    ok, fail = 0, []
    for i, (name, url) in enumerate(todo, 1):
        try:
            body = _fetch(url)
        except Exception as e:  # noqa: BLE001
            print(f"  [{i}/{len(todo)}] ! {name}: {e}", file=sys.stderr)
            fail.append(name)
            continue
        _dest(name).write_text(body, encoding="utf-8")
        has_deck = 'id="Deck"' in body
        print(f"  [{i}/{len(todo)}] {name}  ({len(body)//1024} KB"
              f"{'' if has_deck else ', NO Deck section?'})")
        ok += 1
        if i < len(todo):
            time.sleep(args.delay)

    print(f"\nsaved {ok}, failed {len(fail)}"
          + (f": {', '.join(fail)}" if fail else "")
          + "\nnow run:  ./tt-cli scrape")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
