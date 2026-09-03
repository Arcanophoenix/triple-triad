#!/usr/bin/env python3
"""Download NPC infobox portraits from the FFXIV wiki into reference/NPCs/.

  scripts/fetch_npc_portraits.py                 # every roster NPC missing one
  scripts/fetch_npc_portraits.py --only Buscarron --only Hab
  scripts/fetch_npc_portraits.py --limit 10 --dry-run
  scripts/fetch_npc_portraits.py --force         # re-fetch even if present

For each NPC it fetches the wiki page, picks the infobox portrait (the first
sizeable image that isn't a card / map / quest-marker / rating icon), and saves
the thumbnail the page links into

  reference/NPCs/<name> - Final Fantasy XIV Online Wiki ... _files/<NNNpx-File.ext>

which is exactly where scripts/gui.py's _load_npc_portraits() looks.  NPCs whose
wiki page carries no character portrait (generic mobs) are skipped - the GUI
falls back to an initials tile for them.

Companion to fetch_npc_pages.py (whose index parsing and fetch helper it reuses).
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_npc_pages as fp  # noqa: E402

SITE = "https://ffxiv.consolegameswiki.com"
_IMG = re.compile(r'<img\b[^>]*\bclass="[^"]*mw-file-element[^"]*"[^>]*>')
# chrome / non-portrait images that are also tagged mw-file-element
_BAD = re.compile(
    r"(location|_map\b|_card\.|Rarity|Tick_|TT_[A-Za-z0-9]|Gold_Saucer|[Qq]uest"
    r"|Journal|Aetheryte|Achievement|_icon|Sightseeing|banner|logo|wallpaper"
    r"|promo|screenshot|_key_?art|FFXIV_(?:End|Shadow|Storm|Heaven|Dawn))", re.I)
_REAL = re.compile(
    r"/mediawiki/images/(?:thumb/)?[0-9a-f]/[0-9a-f]{2}/([^/\"?]+\.(?:png|jpe?g))", re.I)


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'\b{name}="([^"]*)"', tag)
    return m.group(1) if m else None


def pick_portrait(page: str) -> tuple[str, str] | None:
    """(thumbnail url, save-as filename) for the page's infobox portrait, or None.

    The infobox picture is the first mw-file-element on the page that is a real
    uploaded image of portrait-ish size and isn't obvious chrome - it sits above
    the location map and the reward-card grid in the source order.
    """
    for m in _IMG.finditer(page):
        tag = m.group(0)
        src = _attr(tag, "src") or ""
        if "/mediawiki/images/" not in src:
            continue
        try:
            fw = int(_attr(tag, "data-file-width") or 0)
            fh = int(_attr(tag, "data-file-height") or 0)
        except ValueError:
            fw = fh = 0
        if fw < 140 or fh < 140:                 # quest markers, rating pips, ...
            continue
        real = _REAL.search(src)
        if not real:
            continue
        fname = urllib.parse.unquote(real.group(1))
        if _BAD.search(fname):
            continue
        url = urllib.parse.urljoin(SITE + "/", src)
        save_as = urllib.parse.unquote(Path(urllib.parse.urlparse(src).path).name)
        stem, dot, ext = save_as.rpartition(".")
        return url, (stem + dot + ext.lower()) if dot else save_as
    return None


def _files_dir(name: str) -> Path:
    p = fp._dest(name)                            # .../<name> ... .html
    return p.with_name(p.stem + "_files")


def _has_portrait(name: str) -> bool:
    d = _files_dir(name)
    if not d.is_dir():
        return False
    for f in d.iterdir():
        low = f.name.lower()
        if f.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            continue
        if f.name.startswith("TT_") or _BAD.search(f.name) or low.endswith("_card.png"):
            continue
        if re.match(r"^\d{1,2}px-", f.name):
            continue
        try:
            if f.stat().st_size >= 4000:
                return True
        except OSError:
            pass
    return False


def _get_bytes(url: str, tries: int = 3) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": fp.UA})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError):
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))
    raise RuntimeError("unreachable")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", action="append", default=[],
                   help="fetch just NPCs whose name contains this (repeatable)")
    p.add_argument("--limit", type=int, default=0, help="stop after N NPCs")
    p.add_argument("--force", action="store_true",
                   help="fetch even for NPCs that already have a portrait on disk")
    p.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    p.add_argument("--dry-run", action="store_true", help="list what would be fetched")
    args = p.parse_args(argv)

    from tt.data import load_npcs
    roster = {n["name"] for n in load_npcs()}
    pairs = fp._pairs(fp._index_path().read_text(encoding="utf-8", errors="replace"), roster)
    if not pairs:
        print("no NPC rows found in the index page", file=sys.stderr)
        return 1
    if args.only:
        subs = [s.lower() for s in args.only]
        pairs = [(n, u) for n, u in pairs if any(s in n.lower() for s in subs)]

    todo = [(n, u) for n, u in pairs if args.force or not _has_portrait(n)]
    if args.limit:
        todo = todo[: args.limit]
    have = sum(1 for n, _ in pairs if _has_portrait(n))
    print(f"{len(pairs)} NPCs in scope; {have} already have a portrait; "
          f"{len(todo)} to try{' (dry run)' if args.dry_run else ''}")
    if args.dry_run:
        for n, u in todo:
            print(f"  {n:32} {u}")
        return 0

    got = none = 0
    fail = []
    for i, (name, url) in enumerate(todo, 1):
        try:
            page = fp._fetch(url)
            pick = pick_portrait(page)
            if not pick:
                none += 1
                print(f"  [{i}/{len(todo)}] {name}: no portrait on the page")
            else:
                img_url, fname = pick
                time.sleep(args.delay)
                data = _get_bytes(img_url)
                d = _files_dir(name)
                d.mkdir(parents=True, exist_ok=True)
                (d / fname).write_bytes(data)
                got += 1
                print(f"  [{i}/{len(todo)}] {name}: {fname}  ({len(data) // 1024} KB)")
        except Exception as e:  # noqa: BLE001
            fail.append(name)
            print(f"  [{i}/{len(todo)}] ! {name}: {e}", file=sys.stderr)
        if i < len(todo):
            time.sleep(args.delay)

    print(f"\nsaved {got} portrait(s); {none} NPC(s) have none on the wiki"
          + (f"; {len(fail)} failed: {', '.join(fail)}" if fail else ""))
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
