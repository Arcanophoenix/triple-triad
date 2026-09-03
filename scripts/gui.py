#!/usr/bin/env python3
"""Local web GUI for the Triple Triad solver.

  scripts/gui.py [port]        # default 8787, opens your browser
  scripts/gui.py 8799 --no-browser   # don't open a tab (scripted / smoke tests)

The Python engine runs behind a stdlib HTTP server; the board is rendered in the
browser (files in gui/).  No third-party dependencies.
"""
from __future__ import annotations

import http.server
import itertools
import json
import multiprocessing
import os
import pathlib
import socketserver
import sys
import time
import urllib.parse
import webbrowser
from concurrent.futures import ProcessPoolExecutor, wait
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tt import paths  # noqa: E402
from tt.collect import apply_export, load_beaten, set_beaten  # noqa: E402
from tt.data import (  # noqa: E402
    CARDS, STARTER_CARDS, deck_draw, find_npc, is_variable_deck, load_collection,
    load_decks, load_npcs, npc_deck_options, resolve,
)
from tt.model import EMPTY_BOARD, GameState, RuleSet, is_terminal, score_a  # noqa: E402
from tt.progress import (  # noqa: E402
    EXPANSIONS, describe as _describe_progress, expansion_of, is_reachable,
    load_progress, npc_patch, save_progress,
)
from tt.recommend import recommend  # noqa: E402
from tt.regions import (  # noqa: E402
    FIXED, MIN_CONSECUTIVE_PAIRS, MIN_DAYS_PER_REGION, REGIONS, by_region,
    clear_regional, cross_region_agreement, effective_rules, is_stale,
    load_history, load_regional, observations, region_for_npc, repeat_rate,
    rule_day, rule_frequency, seed_history, set_regional, weekday_counts,
)
from tt.solver import analyze, apply  # noqa: E402

GUI = paths.GUI_DIR
ICONS = paths.REFERENCE_DIR / (
    "Triple Triad Cards - Final Fantasy XIV Online Wiki - FFXIV _ "
    "FF14 Online Community Wiki and Guide_files"
)
ARR_ART = paths.REFERENCE_DIR / "Cards @ ARR_ Triple Triad - Final Fantasy XIV_files"
ARR_HTML = paths.REFERENCE_DIR / "Cards @ ARR_ Triple Triad - Final Fantasy XIV.html"
_RAW = json.loads((paths.BUNDLED_DATA / "cards.json").read_text(encoding="utf-8"))
_COL_PATH = paths.user_path("collection.json")
_HISTORY_PATH = paths.user_path("history.jsonl")
_STARTER_IDS = {resolve(n).id for n in STARTER_CARDS}
_PARTIAL_BUDGET_S = 25   # wall-clock cap for an exact worst-case-over-unknowns sweep

# "Suggest who to challenge next" solver configs.  The cheap screen (screen_tail
# 4) is biased LOW - measured mean understatement 4.0, worst case 6.0, and never
# once optimistic (see difficulty.py / the regional+difficulty memory).  So a row
# reading a small negative here is very likely a win; the accurate pass
# (screen_tail 6, mean error 1.7) is run on that borderline band within a
# wall-clock budget, cheapest rulesets first.
_SUGGEST_SCREEN = dict(shortlist_n=14, cand_cap=300, screen_tail=4, exact_k=0)
_SUGGEST_ACCURATE = dict(shortlist_n=14, cand_cap=300, screen_tail=6, exact_k=0)
_SUGGEST_BAND = -6.0            # screen values >= this could still be winnable
_SUGGEST_RECHECK_BUDGET_S = 30.0
_SUGGEST_SLOW_RULES = {"Chaos", "Roulette", "Swap"}   # these deepen or fan the solve a lot
# Chaos deepens the endgame tail and Swap doubles the solve per exchange, so an
# accurate re-check of those runs into minutes - too slow to do while the button
# spins.  They keep the (bias-aware) screen value, flagged `screen`.
_SUGGEST_NO_RECHECK = {"Chaos", "Swap"}
_SUGGEST_BUCKET_RANK = {"win": 0, "likely": 1, "close": 2, "notyet": 3, "unknown": 4}


def refine_exact_k(rules) -> int:
    """How many decks the "refine" button solves exactly.

    25 (the CLI default) normally.  The screen ranks decks noisily enough that
    the true best often sits below rank 8 and a narrow slice never reaches it:
    measured on Mother Miounne, exact_k=8 recommends a +6 deck when a +8 one
    exists in the collection, and both it and Jonas only converge - on the margin
    AND on picking the same deck regardless of pool ordering - at 16+.  It is
    close to free because the costly final pass is `top` decks x every draw,
    which exact_k does not touch: 8 -> 25 is about +4s of a ~17s refine.

    Swap is the exception and pays none of that back.  Every deck there is
    already scored as an *average* over the 25 exchanges, which smooths out the
    very screen-ranking noise a wider slice exists to correct - so the best deck
    is inside the top 8 anyway - while the slice itself costs exact_k x 25 x 2
    solves.  Measured on Kaizan: exact_k=8 gives +6.16 in 247s, exact_k=25 gives
    +6.24 in 363s.  116 seconds for 0.08 of margin, on a button a person is sat
    watching.
    """
    return 8 if rules.swap else 25


def _norm_name(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]", "", s.lower()).replace("card", "")


def _load_arr_art() -> dict:
    """card id -> portrait filename in ARR_ART.

    arrtripletriad.com numbers cards differently from the wiki (it interleaves the
    FF-crossover cards), so the portrait files can't be matched by card number -
    match by name instead, from the saved page's own listing.
    """
    out = {}
    if not ARR_HTML.is_file():
        return out
    import html as _html
    import re
    t = ARR_HTML.read_text(encoding="utf-8", errors="replace")
    by_norm = {}
    for block in re.split(r'<li id="card\d+">', t)[1:]:
        mn = re.search(r'<div class="cardNumber">(\d+)</div>', block)
        mnm = re.search(r'<div class="cardName">\s*<a[^>]*>([^<]+)</a>', block)
        if mn and mnm:
            by_norm[_norm_name(_html.unescape(mnm.group(1)))] = mn.group(1)
    for c in CARDS:
        num = by_norm.get(_norm_name(c.name))
        if num and (ARR_ART / f"{num}.png").is_file():
            out[c.id] = f"{num}.png"
    return out


_ARR_BY_ID = _load_arr_art()

NPCS_DIR = paths.REFERENCE_DIR / "NPCs"


def _load_npc_portraits() -> dict:
    """npc name -> a portrait image Path under reference/NPCs/.

    Only ~28 of the 134 NPC wiki pages were ever saved (they were fetched for
    deck scraping), and only those carry an infobox portrait; every other NPC
    falls back to a generated initials tile in the browser.  The file names are
    irregular (``227px-Baderon_render.png``, ``Momodi_portrait.jpg``,
    ``280px-Trachtoum.png``), so rank the non-chrome images in each page's
    ``_files`` dir: a name match wins first, then render > portrait > character
    shot, then the larger rendition.
    """
    import re
    out: dict[str, object] = {}
    if not NPCS_DIR.is_dir():
        return out
    skip = ("_card.png", "_location.", "_map.", "tick_", "featurequest",
            "mainscenarioquest", "sidequest", "dailyquest", "gold_saucer_point",
            "rarity", "tt_card_background")
    names = {n["name"] for n in load_npcs()}
    for d in NPCS_DIR.glob("* - Final Fantasy XIV Online Wiki*_files"):
        npc = d.name.split(" - Final Fantasy")[0]
        if npc not in names:
            continue
        key = re.sub(r"[^a-z]", "", npc.lower())[:6]
        best, best_rank = None, ()
        for f in (*d.glob("*.png"), *d.glob("*.jpg"), *d.glob("*.jpeg")):
            low = f.name.lower()
            if f.name.startswith("TT_") or any(s in low for s in skip):
                continue
            if re.match(r"^\d{1,2}px-", f.name):        # a small chrome icon
                continue
            try:
                if f.stat().st_size < 4000:
                    continue
            except OSError:
                continue
            m = re.match(r"^(\d+)px-", f.name)
            px = int(m.group(1)) if m else 250
            stem = re.sub(r"[^a-z]", "", re.sub(r"^\d+px-", "", low).rsplit(".", 1)[0])
            rank = (bool(key) and key in stem,
                    3 if "render" in low else 2 if "portrait" in low
                    else 1 if "character" in low else 0,
                    px)
            if rank > best_rank:
                best, best_rank = f, rank
        if best is not None:
            out[npc] = best
    return out


_NPC_PORTRAIT = _load_npc_portraits()


def _read_col() -> dict:
    return json.loads(_COL_PATH.read_text(encoding="utf-8")) if _COL_PATH.is_file() else {}


def _write_col(col: dict) -> None:
    paths.ensure_user_dir()
    _COL_PATH.write_text(json.dumps(col, indent=2, ensure_ascii=False) + "\n")


def _owned_ids() -> list[int]:
    """Unique card ids the player owns (starters always included), sorted."""
    ids = set()
    for name in load_collection()["owned"]:
        try:
            ids.add(resolve(name).id)
        except KeyError:
            pass
    return sorted(ids)


def _reward_cards(rec: dict) -> list[dict]:
    """The NPC's prize cards as {id, name} - what you might win off a match."""
    out = []
    for name in rec.get("rewards") or []:
        try:
            c = resolve(name)
        except KeyError:
            continue
        out.append({"id": c.id, "name": c.name})
    return out


def _cards_payload() -> dict:
    return {c.id: {"name": c.name, "sides": list(c.sides), "stars": c.stars,
                   "kind": c.kind, "icon": _RAW[c.id]["icon"]} for c in CARDS}


def _progress_payload() -> dict:
    """Current story progress for the front-end: the raw patch number, a label,
    and the expansion it lands in (so the NPCs tab can pre-tick its filter)."""
    p = load_progress()
    return {"value": p, "label": _describe_progress(p), "expansion": expansion_of(p)}


def _regional_payload() -> dict:
    """Current regional rules for the front-end: every region, the rules recorded
    for it, when, and whether that predates the last daily reset."""
    saved = load_regional()["regions"]
    return {
        "regions": list(REGIONS),
        "current": {r: {"rules": list((saved.get(r) or {}).get("rules") or []),
                        "date": (saved.get(r) or {}).get("date"),
                        "stale": is_stale((saved.get(r) or {}).get("date"))}
                    for r in REGIONS},
    }


# The regional-rules pool the game rolls from (Combo is always on, not a toggle;
# Same Wall is part of Same, not a standalone regional).  Offered as quick chips
# on the Regional tab; the server still accepts any valid rule name.
REGIONAL_RULE_VOCAB = [
    "All Open", "Three Open", "Same", "Plus", "Sudden Death", "Order", "Chaos",
    "Reverse", "Fallen Ace", "Ascension", "Descension", "Swap", "Roulette",
]

_WD = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _regional_overview() -> dict:
    """Everything the Regional tab renders: the per-region board (from
    `_regional_payload`), what is still unlogged for the current rule-day, the
    recent observation log, and the pattern analysis.  Every figure ships with
    its own sample size so a thin log cannot read as a finding."""
    seed_history()                       # fold any pre-log regional.json days in
    obs = observations()
    today = rule_day().isoformat()
    logged = sorted(r for (d, r) in obs if d == today)
    rows_by_region = by_region(obs)
    wdc = weekday_counts(obs)
    days = sorted({d for d, _ in obs})
    rep_same, rep_total = repeat_rate(obs)
    xr_same, xr_total = cross_region_agreement(obs)

    return {
        **_regional_payload(),
        "fixedLabel": FIXED,
        "vocab": REGIONAL_RULE_VOCAB,
        "ruleDay": today,
        "today": {
            "logged": logged,
            "missing": [r for r in REGIONS if r not in logged],
            "rules": {r: obs[(today, r)] for r in logged},
        },
        "history": [{"day": rec["day"],
                     "weekday": _WD[date.fromisoformat(rec["day"]).weekday()],
                     "region": rec["region"],
                     "rules": list(rec.get("rules") or [])}
                    for rec in load_history()[-30:]],
        "pattern": {
            "observations": len(obs),
            "ruleDays": len(days),
            "span": [days[0], days[-1]] if days else None,
            "regions": len(rows_by_region),
            "frequency": {r: {"counts": c.most_common(),
                              "days": len(rows_by_region.get(r, []))}
                          for r, c in rule_frequency(obs).items()},
            "repeat": {"same": rep_same, "total": rep_total},
            "crossRegion": {"same": xr_same, "total": xr_total},
            "weekday": {str(i): (list(wdc[i].most_common()) if i in wdc else [])
                        for i in range(7)},
            "minDaysPerRegion": MIN_DAYS_PER_REGION,
            "minPairs": MIN_CONSECUTIVE_PAIRS,
        },
    }


def _split_deck(spec) -> list[str]:
    if isinstance(spec, list):
        return spec
    spec = spec.strip()
    named = load_collection()["decks"].get(spec)
    if named:
        return list(named)
    return [x.strip() for x in spec.split(",") if x.strip()]


def _opp_of(d: dict) -> str:
    """NPC model for a request/state: 'optimal' unless 'greedy' is explicitly set."""
    return "greedy" if d.get("opp") == "greedy" else "optimal"


def _state_to(s: GameState, opp: str) -> dict:
    return {
        "board": [None if x is None else {"card": x[0], "owner": x[1]} for x in s.board],
        "hands": [list(s.hands[0]), list(s.hands[1])],
        "to_move": s.to_move,
        "rules": s.rules.names(),
        "opp": opp,
        "npcPool": [],
        "terminal": is_terminal(s),
        "scoreYou": score_a(s),
    }


def _state_from(d: dict) -> GameState:
    board = tuple(None if x is None else (x["card"], x["owner"]) for x in d["board"])
    hands = (tuple(d["hands"][0]), tuple(d["hands"][1]))
    return GameState(board, hands, d["to_move"], RuleSet.from_names(d["rules"]))


# --- partial states: a variable-deck NPC whose drawn cards aren't all known yet.
#     hands[1] carries None for an unidentified card; state["npcPool"] lists the
#     card ids those unknowns could still be. ---

def _is_partial(st: dict) -> bool:
    return any(c is None for c in st["hands"][1])


def _holes(hand1) -> list:
    return [i for i, c in enumerate(hand1) if c is None]


def _board_tuple(st: dict):
    return tuple(None if x is None else (x["card"], x["owner"]) for x in st["board"])


def _fill(hand1, holes, cards) -> list:
    h = list(hand1)
    for i, c in zip(holes, cards):
        h[i] = c
    return h


def _completions(st: dict):
    """Concrete GameStates, one per way of filling the NPC's unknown cards."""
    hand1, pool = st["hands"][1], st.get("npcPool", [])
    holes = _holes(hand1)
    board, hand0 = _board_tuple(st), tuple(st["hands"][0])
    rules = RuleSet.from_names(st["rules"])
    for combo in itertools.combinations(pool, len(holes)):
        yield GameState(board, (hand0, tuple(_fill(hand1, holes, combo))),
                        st["to_move"], rules)


def _suggest_bucket(edge, kind) -> str:
    """Coarse winnability class for a suggest row.

    An `accurate` edge is read at face value.  A `screen` edge understates by ~4
    on average and (in the measured sample) was never optimistic, so screen >= 0
    already means you do not lose, and anything down to the worst-case
    understatement (`_SUGGEST_BAND`) is still very likely a win.  "close" is only
    ever reported off an accurate read - the screen cannot tell a real coin-flip
    from its own low bias.
    """
    if edge is None:
        return "unknown"
    if kind == "accurate":
        return ("win" if edge >= 6 else "likely" if edge >= 2
                else "close" if edge >= -1 else "notyet")
    return ("win" if edge >= 0 else "likely" if edge >= _SUGGEST_BAND
            else "notyet")


_SUGGEST_CFG = {"screen": _SUGGEST_SCREEN, "accurate": _SUGGEST_ACCURATE}


def _deck_edge(npc, entry, pool, cfg):
    """Worst-case margin for your best owned deck vs this NPC under `cfg`
    (`_SUGGEST_SCREEN` fast pass / `_SUGGEST_ACCURATE` slow pass); None when it
    cannot be scored (unknown deck shape, or fewer than 5 owned cards)."""
    if len(pool) < 5:
        return None
    rnames = entry.get("rules") or npc.get("rules") or []
    rules = RuleSet.from_names([r.strip() for r in rnames if r.strip()])
    if entry.get("cards"):
        arg = [resolve(x).id for x in entry["cards"]]
    elif is_variable_deck(entry):
        arg = [[resolve(x).id for x in o] for o in npc_deck_options(entry)]
    else:
        return None
    try:
        rec = recommend(arg, rules, pool, opp="greedy", top=1, swaps=False,
                        workers=1, **cfg)      # one NPC per task; recommend stays serial
    except (ValueError, KeyError):
        return None
    return rec.best.worst


def _suggest_edge_job(job):
    npc, entry, pool, cfg_key = job
    return npc["name"], _deck_edge(npc, entry, list(pool), _SUGGEST_CFG[cfg_key])


def _suggest_edges(jobs, cfg_key, *, workers=0, timeout=None):
    """``{npc name: edge}`` for ``jobs`` (each ``(npc, entry, pool)``) scored
    under ``cfg_key``.

    The screen/solve of one NPC is independent of the rest, so this fans across
    a fork pool (``workers=1`` forces serial; used by the tests).  With
    ``timeout`` it returns whatever finished inside that wall-clock window - the
    rest are simply absent from the map, and a couple of long solves already
    running when it elapses are left to finish and exit on their own rather than
    blocking the response.
    """
    tagged = [(npc, entry, pool, cfg_key) for npc, entry, pool in jobs]
    if not tagged:
        return {}
    nw = 1 if workers == 1 else max(1, min(len(tagged), (os.cpu_count() or 2) // 2))

    def _serial():
        out, deadline = {}, (None if timeout is None else time.monotonic() + timeout)
        for j in tagged:
            if deadline is not None and time.monotonic() >= deadline:
                break
            name, edge = _suggest_edge_job(j)
            out[name] = edge
        return out

    if len(tagged) <= 2 or nw <= 1:
        return _serial()
    try:
        ex = ProcessPoolExecutor(max_workers=nw,
                                 mp_context=multiprocessing.get_context("fork"))
    except (OSError, ValueError):
        return _serial()
    try:
        futs = [ex.submit(_suggest_edge_job, j) for j in tagged]
        done, _pending = wait(futs, timeout=timeout)
        out = {}
        for f in done:
            try:
                name, edge = f.result()
                out[name] = edge
            except Exception:                  # a worker raised; drop that NPC
                pass
        return out
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def _partial_state(st_like: dict, board, hand0, hand1, pool, to_move, opp) -> dict:
    return {
        "board": [None if x is None else {"card": x[0], "owner": x[1]} for x in board],
        "hands": [list(hand0), [None if c is None else int(c) for c in hand1]],
        "to_move": to_move,
        "rules": st_like["rules"],
        "opp": opp,
        "npcPool": list(pool),
        "terminal": all(x is not None for x in board) or len((list(hand0), list(hand1))[to_move]) == 0,
        "scoreYou": sum(1 for x in board if x is not None and x[1] == 0) + len(hand0),
    }


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code: int, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _file(self, path: pathlib.Path, ctype: str):
        if not path.is_file():
            return self._send(404, b"not found", "text/plain")
        self._send(200, path.read_bytes(), ctype)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._file(GUI / "index.html", "text/html; charset=utf-8")
        if path == "/app.js":
            return self._file(GUI / "app.js", "text/javascript")
        if path == "/style.css":
            return self._file(GUI / "style.css", "text/css")
        if path.endswith(".png") and "/" not in path[1:]:
            return self._file(GUI / path[1:], "image/png")
        if path.startswith("/icon/"):
            name = urllib.parse.unquote(path[len("/icon/"):])
            f = (ICONS / name).resolve()
            if f.is_file() and f.suffix == ".png" and f.parent == ICONS.resolve():
                return self._file(f, "image/png")
            return self._send(404, b"", "text/plain")
        if path.startswith("/npc-portrait/"):
            npc = urllib.parse.unquote(path[len("/npc-portrait/"):])
            f = _NPC_PORTRAIT.get(npc)                      # curated dict, not a user path
            if f is not None and f.is_file():
                ct = "image/jpeg" if f.suffix.lower() in (".jpg", ".jpeg") else "image/png"
                return self._file(f, ct)
            return self._send(404, b"", "text/plain")
        if path.startswith("/card/") and path.endswith(".png"):
            try:
                cid = int(path[len("/card/"):-4])
            except ValueError:
                return self._send(404, b"", "text/plain")
            if not (0 <= cid < len(CARDS)):
                return self._send(404, b"", "text/plain")
            fname = _ARR_BY_ID.get(cid)                     # ARR portrait art, no numbers
            if fname:
                art = ARR_ART / fname
                if art.is_file():
                    return self._file(art, "image/png")
            icon = (ICONS / _RAW[cid]["icon"]).resolve()    # fall back to the wiki icon
            if icon.is_file() and icon.parent == ICONS.resolve():
                return self._file(icon, "image/png")
            return self._send(404, b"", "text/plain")
        if path == "/api/bootstrap":
            recorded = load_decks()
            return self._send(200, {
                "cards": _cards_payload(),
                "npcs": [{"name": n["name"], "rules": n["rules"],
                          "zone": n["location"]["zone"], "hasDeck": n["name"] in recorded,
                          "region": region_for_npc(n), "patch": n.get("patch"),
                          "expansion": expansion_of(npc_patch(n)),
                          "hasPortrait": n["name"] in _NPC_PORTRAIT,
                          "mgp": n.get("mgp_win") or 0}
                         for n in load_npcs()],
                "decks": recorded,
                "collectionDecks": load_collection()["decks"],
                "ownedIds": _owned_ids(),
                "beaten": sorted(load_beaten()),
                "starterIds": sorted(_STARTER_IDS),
                "regional": _regional_payload(),
                "expansions": [e for e, _ in EXPANSIONS],
                "progress": _progress_payload(),
            })
        if path == "/api/regional":
            return self._send(200, _regional_payload())
        if path == "/api/regionaloverview":
            return self._send(200, _regional_overview())
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "bad json"})
        try:
            if path == "/api/newgame":
                return self._new_game(body)
            if path == "/api/analyze":
                return self._analyze(body)
            if path == "/api/apply":
                return self._apply(body)
            if path == "/api/reveal":
                return self._reveal(body)
            if path == "/api/savedeck":
                return self._save_deck(body)
            if path == "/api/deletedeck":
                return self._delete_deck(body)
            if path == "/api/setowned":
                return self._set_owned(body)
            if path == "/api/setbeaten":
                return self._set_beaten(body)
            if path == "/api/setprogress":
                return self._set_progress(body)
            if path == "/api/import":
                return self._import(body)
            if path == "/api/suggest":
                return self._suggest(body)
            if path == "/api/recommend":
                return self._recommend(body)
            if path == "/api/loggame":
                return self._log_game(body)
            if path == "/api/regional":
                return self._set_regional(body)
        except (KeyError, ValueError) as e:
            return self._send(400, {"error": str(e)})
        return self._send(404, {"error": "not found"})

    @staticmethod
    def _npc_rules(body, entry, rec):
        names = effective_rules(rec, deck_entry=entry, override=body.get("rules"),
                                use_regional=not body.get("noRegional"))
        return RuleSet.from_names([r.strip() for r in names if r.strip()])

    def _set_regional(self, body):
        """Record (or clear) a region's rules.

        `clear: true` or `rules: null` forgets the region.  An *empty* `rules`
        list is a real reading - the screen showed None/None - and is logged as
        such, not treated as "not recorded" (matches `tt-cli regional --none`).
        """
        region = (body.get("region") or "").strip()
        raw = body.get("rules", None)
        if body.get("clear") or raw is None:
            clear_regional(region)
        else:
            rules = [r.strip() for r in (raw.split(",") if isinstance(raw, str) else raw)
                     if r and r.strip()]
            set_regional(region, rules)           # validates region + rule names; [] is None/None
        return self._send(200, _regional_overview())

    @staticmethod
    def _npc_deck_names(body, entry, rec):
        """The NPC's 5 card names for this match.  Handles a fixed deck, a
        variable (fixed + pool) deck where the client picked the pool cards in
        `npcPool`, and a free-text `npcCards` override."""
        if body.get("npcCards"):
            return _split_deck(body["npcCards"])
        if is_variable_deck(entry):
            pool, draw = entry["pool"], deck_draw(entry)
            chosen = body.get("npcPool") or []
            if len(chosen) != draw or any(c not in pool for c in chosen):
                raise ValueError(
                    f"{rec['name']} plays {', '.join(entry['fixed'])} plus {draw} of "
                    f"[{', '.join(pool)}] — pick which {draw} they drew")
            return list(entry["fixed"]) + list(chosen)
        if entry.get("cards"):
            return list(entry["cards"])
        raise ValueError(f"no deck recorded for {rec['name']}; enter their 5 cards")

    def _npc_setup(self, body):
        """(npc name, [5 npc card ids], RuleSet) from a body with npc / npcCards / npcPool / rules."""
        rec = find_npc(body["npc"])
        entry = load_decks().get(rec["name"], {})
        them = [resolve(x).id for x in self._npc_deck_names(body, entry, rec)]
        if len(them) != 5:
            raise ValueError("the NPC deck needs exactly 5 cards")
        return rec["name"], them, self._npc_rules(body, entry, rec)

    def _swap_hands(self, you_ids, entry, rec_name, body, out_q, in_q):
        """Apply the Swap rule: your ``out`` card went to the NPC, their ``in``
        card came to you.  Returns ``(you5, hand1, npc_pool, them5)`` - a partial
        NPC hand + shrunken pool for a variable deck (``them5`` None), or a full
        ``them5`` for a fixed one (``hand1``/``npc_pool`` None)."""
        out_id, in_id = resolve(out_q).id, resolve(in_q).id
        if out_id not in you_ids:
            raise ValueError("the card you swapped away isn't in your deck")
        # Swap can legitimately hand you a second copy of a card you already run
        # (the game allows the duplicate); the solver collapses identical hand
        # cards in legal_moves, so a doubled id is fine.
        you5 = [c for c in you_ids if c != out_id] + [in_id]
        if is_variable_deck(entry):
            fixed = [resolve(x).id for x in entry["fixed"]]
            pool = [resolve(x).id for x in entry["pool"]]
            draw = deck_draw(entry)
            if in_id in fixed:
                hand1 = [out_id if f == in_id else f for f in fixed] + [None] * draw
                npc_pool = [p for p in pool if p != out_id]
            else:                      # a pool card they drew (or, fallback, unknown)
                hand1 = fixed + [out_id] + [None] * (draw - 1)
                npc_pool = [p for p in pool if p not in (in_id, out_id)]
            return you5, hand1, npc_pool, None
        them = [resolve(x).id
                for x in self._npc_deck_names(body, entry, {"name": rec_name})]
        if in_id not in them:
            raise ValueError(f"{rec_name} doesn't hold that card")
        return you5, None, None, [c for c in them if c != in_id] + [out_id]

    def _new_game(self, body):
        rec = find_npc(body["npc"])
        entry = load_decks().get(rec["name"], {})
        rules = self._npc_rules(body, entry, rec)
        you = [resolve(x).id for x in _split_deck(body["deck"])]
        if len(you) != 5:
            raise ValueError("your deck needs exactly 5 cards")
        first = 0 if body.get("youFirst", True) else 1
        # in-match analysis always uses the safe minimax model; _analyze drops to a
        # fast estimate on its own for the slow near-empty / unknown-card positions
        opp = _opp_of(body)

        swap_out, swap_in = body.get("swapOut"), body.get("swapIn")
        if rules.swap and swap_out and swap_in:
            you5, hand1, npc_pool, them5 = self._swap_hands(
                you, entry, rec["name"], body, swap_out, swap_in)
            if them5 is not None:
                s = GameState(EMPTY_BOARD, (tuple(you5), tuple(them5)), first, rules)
                return self._send(200, {"npc": rec["name"], "state": _state_to(s, opp),
                                        "rewards": _reward_cards(rec)})
            state = _partial_state({"rules": rules.names()}, (None,) * 9,
                                   you5, hand1, npc_pool, first, opp)
            resp = {"npc": rec["name"], "state": state, "rewards": _reward_cards(rec)}
            resp["poolInfo"] = {
                "fixed": [CARDS[c].name for c in hand1 if c is not None],
                "pool": [CARDS[c].name for c in npc_pool],
                "draw": sum(1 for c in hand1 if c is None),
            }
            return self._send(200, resp)

        if not body.get("npcCards") and is_variable_deck(entry):
            # start with the pool cards unknown; the human names them as the NPC
            # plays them (or up front, if the rules show the NPC's hand)
            draw = deck_draw(entry)
            pool_ids = [resolve(x).id for x in entry["pool"]]
            picked = [resolve(x).id for x in (body.get("npcPool") or [])]
            if any(p not in pool_ids for p in picked):
                raise ValueError("a pre-picked pool card isn't in the pool")
            picked = picked[:draw]
            hand1 = ([resolve(x).id for x in entry["fixed"]] + picked
                     + [None] * (draw - len(picked)))
            remaining = [p for p in pool_ids if p not in picked]
            state = _partial_state(
                {"rules": rules.names()}, (None,) * 9, you, hand1, remaining, first, opp)
            return self._send(200, {
                "npc": rec["name"], "state": state, "rewards": _reward_cards(rec),
                "poolInfo": {"fixed": entry["fixed"], "pool": entry["pool"], "draw": draw},
            })

        name, them, r = self._npc_setup(body)
        s = GameState(EMPTY_BOARD, (tuple(you), tuple(them)), first, r)
        self._send(200, {"npc": name, "state": _state_to(s, opp),
                         "rewards": _reward_cards(rec)})

    def _analyze(self, body):
        st = body["state"]
        opp = _opp_of(st)
        if not _is_partial(st):
            s = _state_from(st)
            if is_terminal(s):
                return self._send(200, {"terminal": True})
            empty = sum(1 for x in s.board if x is None)
            # an optimal solve from a near-empty board runs for seconds (up to ~15s
            # under Plus/Same); use the fast model there, exact once the board fills
            model = "greedy" if (opp == "optimal" and empty > 5) else opp
            a = analyze(s, opp=model)
            hand = s.hands[s.to_move]
            return self._send(200, {
                "terminal": False,
                "toMove": s.to_move,
                "approx": model != opp,
                "model": model,
                "best": {"card": hand[a.best.hand_idx], "cell": a.best.cell, "value": a.best.value},
                "ranked": [{"card": hand[r.hand_idx], "cell": r.cell, "value": r.value}
                           for r in a.ranked],
            })
        # partial: the client only analyses on your turn, so score each move by its
        # worst case over every card the NPC might still be holding.  An exact
        # sweep of several completions early in the game (esp. under Plus) can run
        # for minutes, so cap it: fall back to the fast greedy model when the
        # exact sweep is too big, and hard-stop the sweep at a wall-clock budget.
        hand0 = st["hands"][0]
        comps = [cs for cs in _completions(st) if not is_terminal(cs)]
        if not comps:
            return self._send(200, {"terminal": True})
        empty = sum(1 for x in st["board"] if x is None)
        fast = opp == "optimal" and len(comps) > 1 and empty > 5
        approx = fast
        deadline = time.monotonic() + _PARTIAL_BUDGET_S
        agg: dict = {}
        for cs in comps:
            model = "greedy" if fast else opp
            if not fast and model == "optimal" and time.monotonic() > deadline:
                model, approx = "greedy", True
            a = analyze(cs, opp=model)
            for r in a.ranked:
                agg.setdefault((r.hand_idx, r.cell), []).append(r.value)
        rows = sorted(((hi, ce, min(v), max(v)) for (hi, ce), v in agg.items()),
                      key=lambda t: (t[2], t[3]), reverse=True)
        bhi, bce, bw, bb = rows[0]
        self._send(200, {
            "terminal": False, "toMove": st["to_move"], "uncertain": True,
            "combos": len(comps), "approx": approx,
            "model": "greedy" if approx else opp,
            "best": {"card": hand0[bhi], "cell": bce, "value": bw, "best": bb},
            "ranked": [{"card": hand0[hi], "cell": ce, "value": w, "best": b}
                       for hi, ce, w, b in rows],
        })

    def _apply(self, body):
        st = body["state"]
        cid, cell = body["card"], body["cell"]
        if not (0 <= cell < 9) or st["board"][cell] is not None:
            raise ValueError("cell is taken or out of range")
        if not _is_partial(st):
            s = _state_from(st)
            hand = s.hands[s.to_move]
            if cid not in hand:
                raise ValueError("that card isn't in the current hand")
            ns = apply(s, hand.index(cid), cell)
            return self._send(200, {"state": _state_to(ns, _opp_of(st))})

        to_move = st["to_move"]
        hand1 = st["hands"][1]
        if to_move == 0 and cid not in st["hands"][0]:
            raise ValueError("that card isn't in your hand")
        if to_move == 1 and (cid is None or cid not in hand1):
            raise ValueError("name the NPC's card first (click it in the 'not yet seen' row)")
        holes = _holes(hand1)
        pool = list(st.get("npcPool", []))
        if len(pool) < len(holes):
            raise ValueError("not enough pool cards left to fill the NPC's hand")
        fillers = pool[:len(holes)]
        s = GameState(_board_tuple(st),
                      (tuple(st["hands"][0]), tuple(_fill(hand1, holes, fillers))),
                      to_move, RuleSet.from_names(st["rules"]))
        ns = apply(s, list(s.hands[to_move]).index(cid), cell)
        left, out1 = list(fillers), []
        for x in ns.hands[1]:
            if x in left:
                left.remove(x)
                out1.append(None)
            else:
                out1.append(x)
        state = _partial_state(st, ns.board, ns.hands[0], out1, pool,
                               ns.to_move, _opp_of(st))
        self._send(200, {"state": state})

    def _reveal(self, body):
        """Name one of the NPC's face-down cards (a pool card) once you've seen it."""
        st = body["state"]
        cid = body["card"]
        hand1 = list(st["hands"][1])
        pool = list(st.get("npcPool", []))
        holes = _holes(hand1)
        if not holes:
            raise ValueError("the NPC's cards are all identified already")
        if cid not in pool:
            raise ValueError("that isn't one of the NPC's possible pool cards")
        hand1[holes[0]] = cid
        pool.remove(cid)
        out = dict(st)
        out["hands"] = [list(st["hands"][0]), hand1]
        out["npcPool"] = pool
        self._send(200, {"state": out})

    def _log_game(self, body):
        """Append a finished match to data/history.jsonl for later `tt-cli review`.

        Stored raw (deck, rules, first, opp, the move list, revealed pool cards,
        final score); the verdict - did the outcome match the solver's read, did
        every move follow the recommendation - is recomputed at review time.
        """
        def _cid(x):
            i = x if isinstance(x, int) else resolve(x).id
            if not (0 <= i < len(CARDS)):
                raise ValueError(f"card id out of range: {x}")
            return i
        try:
            deck = [_cid(x) for x in body["deck"]]
            moves = [[int(s), _cid(c), int(p)] for s, c, p in body.get("moves", [])]
            revealed = [_cid(x) for x in body.get("revealed", [])]
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"bad game log: {e}")
        if len(deck) != 5:
            raise ValueError("deck needs 5 cards")
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "npc": str(body.get("npc", "")).strip(),
            "rules": [str(r) for r in body.get("rules", [])],
            "deck": deck,
            "youFirst": bool(body.get("youFirst", True)),
            "opp": _opp_of(body),
            "moves": moves,
            "revealed": revealed,
            "scoreYou": int(body.get("scoreYou", 0)),
        }
        paths.ensure_user_dir()
        with _HISTORY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        n = sum(1 for _ in _HISTORY_PATH.open(encoding="utf-8"))
        self._send(200, {"logged": True, "count": n})

    def _save_deck(self, body):
        name = str(body.get("name", "")).strip()
        if not name or name == "starter":
            raise ValueError("give the deck a name (not 'starter')")
        cards = [resolve(x) for x in body["cards"]]
        if len(cards) != 5:
            raise ValueError("a deck needs exactly 5 cards")
        if len({c.id for c in cards}) != 5:
            raise ValueError("no duplicate cards")
        if sum(c.stars >= 4 for c in cards) > 1:
            raise ValueError("a deck may only hold one 4-5 star card")
        col = _read_col()
        col.setdefault("decks", {})[name] = [c.name for c in cards]
        _write_col(col)
        self._send(200, {"collectionDecks": load_collection()["decks"]})

    def _delete_deck(self, body):
        name = str(body.get("name", "")).strip()
        col = _read_col()
        if name in col.get("decks", {}):
            del col["decks"][name]
            _write_col(col)
        self._send(200, {"collectionDecks": load_collection()["decks"]})

    def _set_owned(self, body):
        card = resolve(body["card"])
        want = bool(body.get("owned"))
        col = _read_col()
        seen, names = set(), []
        for x in col.get("owned", []):
            try:
                c = resolve(x)
            except KeyError:
                continue
            if c.id not in seen:
                seen.add(c.id)
                names.append(c.name)
        if want and card.id not in seen:
            names.append(card.name)
        elif not want and card.id in seen and card.id not in _STARTER_IDS:
            names = [n for n in names if resolve(n).id != card.id]
        col["owned"] = names
        _write_col(col)
        self._send(200, {"ownedIds": _owned_ids()})

    def _set_beaten(self, body):
        """Tick/untick one NPC as beaten.  Matched through find_npc so the client
        can send whatever spelling it has, then stored under the roster's own
        name - the same names an FFXIV Collect import writes."""
        npc = find_npc(body["npc"])
        self._send(200, {"beaten": set_beaten(npc["name"], bool(body.get("beaten")))})

    def _set_progress(self, body):
        """Record story progress (an expansion name, a patch number, or null to
        clear).  Everything from later content then drops off the NPCs list and
        the challenge suggestion."""
        try:
            value = save_progress(body.get("progress"))
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        self._send(200, _progress_payload() if value is None else {
            "value": value, "label": _describe_progress(value),
            "expansion": expansion_of(value)})

    def _import(self, body):
        """Fold a parsed FFXIV Collect export into the collection.  The browser
        reads the file and posts its JSON here as {"export": {...}}; merges by
        default (only ever gains cards / wins), replace=true makes it
        authoritative."""
        data = body.get("export")
        if not isinstance(data, dict):
            return self._send(400, {"error": "no export object in the request"})
        if not ({"cards", "npcs"} & set(data)):
            return self._send(400, {"error": "that file has no 'cards' or 'npcs' "
                                             "list - is it an FFXIV Collect export?"})
        r = apply_export(data, replace=bool(body.get("replace")))
        r["ownedIds"] = _owned_ids()
        r["beaten"] = sorted(load_beaten())
        self._send(200, r)

    def _suggest(self, body):
        """Rank the NPCs worth challenging next: reachable given story progress,
        not yet beaten, deck on record, ordered by how comfortably you take them.

        Every candidate gets the cheap screen first (fast, but biased LOW by ~4
        and never optimistic).  The rows that screen near or below zero - where
        that bias could be hiding a winnable match - are then re-scored with the
        accurate config, cheapest rulesets first, within a wall-clock budget; the
        rest keep the screen value, flagged as such.  Both passes fan across
        processes (one NPC per task).  `body["fast"]` skips the re-score;
        `tt-cli difficulty --challenge` is the full, unbounded version.
        """
        limit = max(1, min(int(body.get("limit") or 10), 25))
        fast = bool(body.get("fast"))
        budget = float(body.get("budget") or _SUGGEST_RECHECK_BUDGET_S)
        workers = int(body.get("workers") or 0)
        progress = load_progress()
        beaten = load_beaten()
        decks = load_decks()
        pool = _owned_ids()

        cands = []
        for n in load_npcs():
            if n["name"] in beaten or n["name"] not in decks:
                continue
            if progress is not None and not is_reachable(n, progress):
                continue
            cands.append(n)
        cands.sort(key=lambda n: (n.get("mgp_win") or 0, n["name"]))
        considered = len(cands)
        picks = cands[:limit]
        entries = {n["name"]: decks[n["name"]] for n in picks}

        screen = _suggest_edges([(n, entries[n["name"]], pool) for n in picks],
                                "screen", workers=workers)
        rows = [{"npc": n, "entry": entries[n["name"]],
                 "edge": screen.get(n["name"]),
                 "kind": None if screen.get(n["name"]) is None else "screen"}
                for n in picks]

        rechecked = 0
        if not fast and len(pool) >= 5:
            band = [r for r in rows
                    if r["edge"] is not None and _SUGGEST_BAND <= r["edge"] < 6.0
                    and not self._too_slow_to_recheck(r["npc"], r["entry"])]
            band.sort(key=lambda r: (self._recheck_cost(r["npc"], r["entry"]), -r["edge"]))
            acc = _suggest_edges([(r["npc"], r["entry"], pool) for r in band],
                                 "accurate", workers=workers,
                                 timeout=max(0.0, budget))
            for r in band:
                v = acc.get(r["npc"]["name"])
                if v is not None:
                    r["edge"], r["kind"] = v, "accurate"
                    rechecked += 1

        out = []
        for r in rows:
            n = r["npc"]
            bucket = _suggest_bucket(r["edge"], r["kind"])
            out.append({"name": n["name"], "zone": n["location"]["zone"],
                        "rules": n["rules"], "mgp": n.get("mgp_win") or 0,
                        "expansion": expansion_of(npc_patch(n)),
                        "hasPortrait": n["name"] in _NPC_PORTRAIT,
                        "edge": r["edge"], "edgeKind": r["kind"], "bucket": bucket})
        out.sort(key=lambda r: (_SUGGEST_BUCKET_RANK[r["bucket"]],
                                -(r["edge"] if r["edge"] is not None else -99),
                                r["mgp"]))
        self._send(200, {
            "suggestions": out,
            "consideredOf": considered,
            "rechecked": rechecked,
            "progress": _progress_payload(),
        })

    @staticmethod
    def _npc_rule_set(npc, entry) -> set:
        return set(entry.get("rules") or npc.get("rules") or [])

    @classmethod
    def _recheck_cost(cls, npc, entry) -> int:
        """Cheap proxy for how long an accurate solve of this NPC will take, so
        the budgeted re-score does the quick ones first: Chaos / Roulette / Swap
        each deepen or fan the solve by a large factor."""
        return len(cls._npc_rule_set(npc, entry) & _SUGGEST_SLOW_RULES)

    @classmethod
    def _too_slow_to_recheck(cls, npc, entry) -> bool:
        """Chaos / Swap put an accurate solve into the minutes - not worth
        starting for a live suggestion; the screen value stands."""
        return bool(cls._npc_rule_set(npc, entry) & _SUGGEST_NO_RECHECK)

    def _recommend(self, body):
        rec_npc = find_npc(body["npc"])
        entry = load_decks().get(rec_npc["name"], {})
        rules = self._npc_rules(body, entry, rec_npc)

        note = ""
        if rules.roulette:
            fixed = [n for n in rules.names() if n != "Roulette"]
            note = ("Roulette NPC — deck picked under "
                    + (f"the always-on rules ({', '.join(fixed)})" if fixed else "plain rules")
                    + "; the roll is only known at match start")
        if not body.get("npcCards") and not body.get("npcPool") and is_variable_deck(entry):
            # deck only known up to the random draw: score every possibility, worst case
            opts = npc_deck_options(entry)
            npc_arg = [[resolve(x).id for x in o] for o in opts]
            drawn = (f"worst case across {rec_npc['name']}'s {len(opts)} possible decks "
                     f"({len(entry['fixed'])} fixed + {deck_draw(entry)} of "
                     f"{len(entry['pool'])})")
            note = f"{note}  ·  {drawn}" if note else drawn
        else:
            npc_names = self._npc_deck_names(body, entry, rec_npc)
            npc_arg = [resolve(x).id for x in npc_names]
            if len(npc_arg) != 5:
                raise ValueError("the NPC deck needs exactly 5 cards")

        pool = _owned_ids()
        if len(pool) < 5:
            raise ValueError("mark at least 5 owned cards in Manage first")
        refine = bool(body.get("refine"))

        # Stream newline-delimited JSON: any number of {"type":"progress",...}
        # events, then one {"type":"result",...} or {"type":"error",...}.  A
        # recommend run gives no feedback otherwise - the screening pass alone can
        # run for minutes on a big pool / a many-draw NPC.
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        class _Gone(Exception):
            pass

        def emit(obj):
            try:
                self.wfile.write((json.dumps(obj) + "\n").encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                raise _Gone

        try:
            rec = recommend(
                npc_arg, rules, pool, opp="greedy", swaps=False,
                top=4 if refine else 6,
                shortlist_n=16 if refine else 14,
                cand_cap=900 if refine else 400,
                screen_tail=6 if refine else 4,
                exact_k=refine_exact_k(rules) if refine else 0,
                # refine fans out; so does a Swap NPC, where the estimate is 25x
                # the work per candidate.  Otherwise the estimate is already <1s.
                workers=0 if (refine or rules.swap) else 1,
                progress=lambda e: emit({"type": "progress", **e}),
            )
        except _Gone:
            return                                   # client went away mid-run
        except Exception as e:                        # noqa: BLE001 - report, don't 500
            try:
                emit({"type": "error", "error": str(e) or e.__class__.__name__})
            except _Gone:
                pass
            return

        try:
            emit({
                "type": "result",
                "npc": rec_npc["name"],
                "rules": rules.names(),
                "screened": rec.screened,
                "refined": refine,
                "note": note,
                "results": [{"cards": r.names(), "first": r.first, "second": r.second,
                             "worst": r.worst, "avg": r.avg, "exact": r.exact}
                            for r in rec.results],
            })
        except _Gone:
            pass


def main() -> int:
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    argv = [a for a in sys.argv[1:] if a != "--no-browser"]
    no_browser = "--no-browser" in sys.argv     # for scripted/smoke-test runs
    want = int(argv[0]) if argv else 8787
    explicit = bool(argv)
    srv = None
    tried = []
    for port in ([want] if explicit else range(want, want + 20)):
        try:
            srv = socketserver.ThreadingTCPServer(("127.0.0.1", port), Handler)
            break
        except OSError as e:
            tried.append(port)
            last = e
    if srv is None:
        where = f"127.0.0.1:{want}" if explicit else f"127.0.0.1:{tried[0]}-{tried[-1]}"
        print(f"can't bind {where} ({last}). Another copy is probably still running - "
              f"close it, or pass a free port:  TripleTriad gui {want + 100}")
        return 1
    port = srv.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    print(f"Triple Triad GUI  ->  {url}   (Ctrl-C to stop)")
    print(f"data folder: {paths.USER_DIR}")
    if not no_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
