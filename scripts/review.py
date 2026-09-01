#!/usr/bin/env python3
"""Replay finished matches from data/history.jsonl and check the solver against them.

  scripts/review.py                # one row per logged game
  scripts/review.py 7              # replay game #7 move by move
  scripts/review.py --summary      # aggregate: was the solver right?
  scripts/review.py --npc Momodi   # filter the list to one NPC

Every game the GUI finishes is appended to data/history.jsonl (raw: your deck,
rules, who led, the NPC model, the move list, revealed pool cards, final score).
This tool re-solves each position and reports:

  * predicted - the solver's your-margin from the opening position
  * actual    - the real final margin
  * followed  - your turns where the played move matched the recommendation
  * NPC vs model - NPC turns where the NPC deviated from the modelled move,
                   and whether that helped (+) or hurt (-) you
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
import multiprocessing
import os
import pathlib
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations

warnings.filterwarnings("ignore", message=r".*multi-threaded.*fork\(\).*",
                        category=DeprecationWarning)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tt import paths  # noqa: E402
from tt.data import (  # noqa: E402
    CARDS, find_npc, is_variable_deck, load_decks, resolve,
)
from tt.model import EMPTY_BOARD, GameState, RuleSet, is_terminal, value_a  # noqa: E402
from tt.recommend import CHAOS_TAIL, screen_value  # noqa: E402
from tt.solver import analyze, apply  # noqa: E402

HISTORY = paths.user_path("history.jsonl")
VCACHE = paths.user_path(".review_cache.json")
_MAX_COMPS = 6           # cap NPC-hand completions weighed for the prediction band


# --- solve memo: many logged games repeat the same positions (same NPC, same
#     deck, same opening) so re-solving each from scratch is wasteful. ---

def _pos_key(st: GameState, opp: str, forced_hand_idx: int | None = None):
    return (st.board, st.hands, st.to_move, tuple(st.rules.names()), opp,
            forced_hand_idx)


def _chaos_rank(st: GameState, forced: int, opp: str):
    """Rank the cells for a dealt card under Chaos, same shape as a solved result.

    Not ``analyze``: it would solve each candidate cell to a full board, and every
    Chaos ply is an unprunable expectimax node, so ply 1 alone runs ~5 minutes and
    review re-solves every game.  Each cell is scored with the same graded
    estimate the recommender uses instead - which is exact once the board has
    filled past the screen's tail, so late plies (where the interesting mistakes
    are) are solved outright and only the opening is approximated.
    """
    cells = [i for i in range(9) if st.board[i] is None]
    if len(cells) == 9:
        cells = [0, 1, 4]
    ranked = []
    for c in cells:
        child = apply(st, forced, c)
        v = value_a(child) if is_terminal(child) else screen_value(child, CHAOS_TAIL, opp)
        ranked.append((forced, c, v))
    ranked.sort(key=lambda r: r[2], reverse=st.to_move == 0)
    best = ranked[0]
    return (best[0], best[1], best[2], tuple(ranked))


@functools.lru_cache(maxsize=None)
def _solve_key(key):
    board, hands, to_move, rule_names, opp, forced = key
    rules = RuleSet.from_names(list(rule_names))
    st = GameState(board, hands, to_move, rules)
    if rules.chaos:
        return None if forced is None else _chaos_rank(st, forced, opp)
    try:
        a = analyze(st, forced_hand_idx=forced, opp=opp)
    except ValueError:
        return None
    return (a.best.hand_idx, a.best.cell, a.best.value,
            tuple((r.hand_idx, r.cell, r.value) for r in a.ranked))


def _solve(st: GameState, opp: str, forced_hand_idx: int | None = None):
    """(best_hand_idx, best_cell, best_value, ranked) for a position, memoised.

    Under Chaos the mover does not choose the card, so ``analyze`` refuses to
    rank moves without being told which one they were dealt - pass the index of
    the card the log says was actually played and the ranking is over cells.
    That is the only question worth asking of a Chaos turn anyway: given the card
    you were handed, was that the best square for it?
    """
    return _solve_key(_pos_key(st, opp, forced_hand_idx))


def _load() -> list[dict]:
    if not HISTORY.is_file():
        return []
    out = []
    for line in HISTORY.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _ids(names) -> list[int]:
    return [resolve(x).id for x in names]


def _short(cid: int) -> str:
    return CARDS[cid].name.removesuffix(" Card")


def _rules(g: dict) -> RuleSet:
    return RuleSet.from_names([r.strip() for r in g.get("rules", []) if str(r).strip()])


def _npc_completions(g: dict) -> list[list[int]]:
    """Every NPC 5-card hand consistent with the game: the cards the NPC played
    or revealed, filled out from the recorded deck if we saw fewer than five."""
    seen = list(dict.fromkeys([c for s, c, _ in g["moves"] if s == 1] + g.get("revealed", [])))
    if len(seen) >= 5:
        return [seen[:5]]
    try:
        entry = load_decks().get(find_npc(g["npc"])["name"], {})
    except KeyError:
        entry = {}
    need = 5 - len(seen)
    if entry.get("cards"):
        rest = [c for c in _ids(entry["cards"]) if c not in seen]
        return [seen + rest[:need]] if len(rest) >= need else []
    if is_variable_deck(entry):
        pool = [c for c in _ids(entry["pool"]) + _ids(entry["fixed"]) if c not in seen]
        combos = [seen + list(x) for x in combinations(pool, need)]
        return combos[:_MAX_COMPS]                       # cap the prediction-band work
    return []


def _opening_value(deck: list[int], npc5: list[int], first: int, rules: RuleSet,
                   opp: str) -> float | None:
    st = GameState(EMPTY_BOARD, (tuple(deck), tuple(npc5)), first, rules)
    if is_terminal(st):
        return None
    if rules.chaos:
        # No opening card was dealt yet, so there is no forced index to pass, and
        # a full Chaos solve from an empty board is out of reach (every ply is an
        # expectimax node - hours).  Same deep-screen estimate the recommender
        # uses; the verdict is flagged approximate so the number is not read as a
        # solved prediction.
        return screen_value(st, CHAOS_TAIL, opp)
    a = _solve(st, opp)                                  # your-margin, best play both sides
    return None if a is None else a[2]


def _replay(g: dict, npc5: list[int]):
    """Yield (ply, side, played_card, cell, note-dict) walking the logged moves."""
    rules = _rules(g)
    first = 0 if g["youFirst"] else 1
    st = GameState(EMPTY_BOARD, (tuple(g["deck"]), tuple(npc5)), first, rules)
    for ply, (side, card, cell) in enumerate(g["moves"], 1):
        note: dict = {}
        hand = st.hands[st.to_move]
        if st.to_move != side or card not in hand:
            note["error"] = f"move {ply} not legal for the state"
            yield ply, side, card, cell, note
            return
        # under Chaos the card was dealt, not chosen - rank cells for that card
        forced = hand.index(card) if rules.chaos else None
        a = _solve(st, g["opp"], forced)                 # (best_hi, best_cell, best_val, ranked)
        if a is not None:
            best_hi, best_cell, best_val, ranked = a
            if side == 0:
                pv = next((rv for rhi, rc, rv in ranked
                           if st.hands[0][rhi] == card and rc == cell), None)
                note["followed"] = pv is not None and pv == best_val
                note["rec"] = (st.hands[0][best_hi], best_cell)
            else:
                exp_card = st.hands[1][best_hi]
                note["rec"] = (exp_card, best_cell)
                note["deviated"] = (exp_card, best_cell) != (card, cell)
                after = apply(st, hand.index(card), cell)
                if is_terminal(after):
                    v_actual = value_a(after)
                elif rules.chaos:
                    # same units as best_val above, which is also a screen value;
                    # _solve without a dealt card returns None under Chaos, and
                    # falling back to value_a() would compare a mid-board margin
                    # against a game value
                    v_actual = screen_value(after, CHAOS_TAIL, g["opp"])
                else:
                    aa = _solve(after, g["opp"])
                    v_actual = value_a(after) if aa is None else aa[2]
                note["swing"] = v_actual - best_val          # + helped you, - hurt you
        st = apply(st, hand.index(card), cell)
        yield ply, side, card, cell, note


# bump when the verdict maths changes.  3: the Ascension/Descension placed-card
# exclusion and the Fallen Ace 1-vs-A correction both change capture resolution.
# 4: Chaos games used to be skipped entirely (no prediction, no followed count);
# they now replay against the card the log says was dealt.
_VERDICT_VERSION = 4
_VCACHE_DATA: dict | None = None


def _vcache() -> dict:
    global _VCACHE_DATA
    if _VCACHE_DATA is None:
        try:
            _VCACHE_DATA = json.loads(VCACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _VCACHE_DATA = {}
    return _VCACHE_DATA


def _vkey(g: dict) -> str:
    raw = f"{_VERDICT_VERSION}|" + json.dumps(g, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _verdict(g: dict) -> dict:
    """{predicted:[lo,hi]|None, actual, followed:[n,of], npc_dev, npc_cost, error}.

    Cached to data/.review_cache.json keyed by the game record - the first
    `review` after new games is slow, later runs are instant.
    """
    cache = _vcache()
    key = _vkey(g)
    if key in cache:
        return cache[key]
    v = _verdict_compute(g)
    cache[key] = v
    return v


def _verdict_compute(g: dict) -> dict:
    rules = _rules(g)
    first = 0 if g["youFirst"] else 1
    comps = _npc_completions(g)
    actual = 2 * g["scoreYou"] - 10
    v = {"predicted": None, "actual": actual, "followed": [0, 0],
         "npc_dev": 0, "npc_cost": 0.0, "npc5_known": bool(comps and len(comps) == 1),
         # Chaos cannot be solved to a full board, so its numbers are estimates
         "approx": bool(rules.chaos), "error": None}
    if not comps:
        v["error"] = "NPC deck unknown"
        return v
    vals = [x for x in (_opening_value(g["deck"], c, first, rules, g["opp"]) for c in comps)
            if x is not None]
    if vals:
        v["predicted"] = [min(vals), max(vals)]
    foll_n = foll_of = dev = 0
    cost = 0.0
    for _ply, side, _c, _cell, note in _replay(g, comps[0]):
        if note.get("error"):
            v["error"] = note["error"]
            break
        if side == 0 and "followed" in note:
            foll_of += 1
            foll_n += int(note["followed"])
        if side == 1 and note.get("deviated"):
            dev += 1
            cost += min(0.0, note.get("swing", 0.0))     # only count moves that hurt you
    v["followed"] = [foll_n, foll_of]
    v["npc_dev"] = dev
    v["npc_cost"] = cost
    return v


def _save_vcache() -> None:
    if _VCACHE_DATA is not None:
        try:
            paths.ensure_user_dir()
            VCACHE.write_text(json.dumps(_VCACHE_DATA), encoding="utf-8")
        except OSError:
            pass


def _verdict_job(g: dict):
    return _vkey(g), _verdict_compute(g)


def _nice_init():                        # pragma: no cover
    try:
        if hasattr(os, "nice"):
            os.nice(19)
    except OSError:
        pass


def warm_cache(games: list[dict]) -> None:
    """Solve every not-yet-cached game up front, in parallel (idle priority).
    The first `review` after new matches pays this; later runs are instant."""
    cache = _vcache()
    missing = [g for g in games if _vkey(g) not in cache]
    if not missing:
        return
    missing.sort(key=lambda g: (g["npc"], tuple(g["deck"]), g["youFirst"]))  # group for the solve memo
    nw = max(1, (os.cpu_count() or 2) // 2)
    print(f"solving {len(missing)} game(s) - first run only…", file=sys.stderr, flush=True)
    ex = None
    if len(missing) > 2 and nw > 1:
        try:
            ex = ProcessPoolExecutor(max_workers=nw,
                                     mp_context=multiprocessing.get_context("fork"),
                                     initializer=_nice_init)
        except (OSError, ValueError):
            ex = None
    try:
        if ex is None:
            for i, g in enumerate(missing, 1):
                cache[_vkey(g)] = _verdict_compute(g)
                print(f"  {i}/{len(missing)}", end="\r", file=sys.stderr, flush=True)
        else:
            cs = max(1, len(missing) // (nw * 2))
            for i, (k, v) in enumerate(ex.map(_verdict_job, missing, chunksize=cs), 1):
                cache[k] = v
                print(f"  {i}/{len(missing)}", end="\r", file=sys.stderr, flush=True)
    finally:
        if ex is not None:
            ex.shutdown(wait=False, cancel_futures=True)
    print(file=sys.stderr)
    _save_vcache()


def _pred_txt(pred) -> str:
    if pred is None:
        return "?"
    lo, hi = pred
    f = lambda x: ("+" if x > 0 else "") + f"{x:g}"
    return f(lo) if lo == hi else f"{f(lo)}..{f(hi)}"


def _hit(pred, actual) -> str:
    if pred is None:
        return "-"
    lo, hi = pred
    return "match" if lo <= actual <= hi else "OFF"


def cmd_list(games, args) -> int:
    rows = list(enumerate(games, 1))
    if args.npc:
        q = args.npc.lower()
        rows = [(i, g) for i, g in rows if q in g["npc"].lower()]
    if not rows:
        print("no games logged yet - finish a match in the GUI" if not games else "no games match")
        return 0
    print(f"{'#':>3}  {'date':16}  {'NPC':22} {'rules':16} {'lead':5} {'model':7} "
          f"{'pred':>9} {'actual':>6} {'':5} {'followed':>8} {'NPC vs model'}")
    print("-" * 118)
    for i, g in rows:
        v = _verdict(g)
        dev = "-" if not v["npc_dev"] else (
            f"{v['npc_dev']} dev" + (f", -{abs(v['npc_cost']):g}" if v["npc_cost"] else ", ~"))
        fo = v["followed"]
        print(f"{i:>3}  {g.get('ts', '?')[:16]:16}  {g['npc'][:22]:22} "
              f"{(', '.join(g['rules']) or '-')[:16]:16} "
              f"{'you' if g['youFirst'] else 'NPC':5} {g['opp']:7} "
              f"{_pred_txt(v['predicted']):>9} {v['actual']:>+6} {_hit(v['predicted'], v['actual']):5} "
              f"{(str(fo[0]) + '/' + str(fo[1])):>8} {dev}"
              + (f"   ! {v['error']}" if v['error'] else ""))
    return 0


def cmd_show(games, n: int) -> int:
    if not (1 <= n <= len(games)):
        print(f"no game #{n} (have 1..{len(games)})")
        return 1
    g = games[n - 1]
    comps = _npc_completions(g)
    v = _verdict(g)
    print(f"game #{n}  -  {g.get('ts', '?')}")
    print(f"  {g['npc']}   rules: {', '.join(g['rules']) or 'none'}   "
          f"{'you lead' if g['youFirst'] else 'NPC leads'}   model: {g['opp']}")
    print(f"  your deck : {', '.join(_short(c) for c in g['deck'])}")
    if comps:
        tag = "" if len(comps) == 1 else f"  (one of {len(comps)} possible draws)"
        print(f"  NPC hand  : {', '.join(_short(c) for c in comps[0])}{tag}")
    print(f"  predicted your-margin: {_pred_txt(v['predicted'])}    "
          f"actual: {v['actual']:+d}    -> {_hit(v['predicted'], v['actual'])}")
    if v.get("approx"):
        print("  (Chaos: you do not pick the card, so every position here is a deep "
              "estimate, not a solved value - and 'followed' means you played the "
              "best cell for the card you were dealt)")
    if v["error"]:
        print(f"  ! {v['error']}")
        return 0
    print(f"\n  {'ply':>3} {'who':4} {'played':>22}  {'solver said':>22}  note")
    print("  " + "-" * 74)
    for ply, side, card, cell, note in _replay(g, comps[0]):
        who = "you" if side == 0 else "NPC"
        played = f"{_short(card)} -> {cell + 1}"
        rec = note.get("rec")
        rec_s = f"{_short(rec[0])} -> {rec[1] + 1}" if rec else "-"
        if side == 0:
            tag = "ok" if note.get("followed") else "DIFFERENT from rec"
        else:
            if note.get("deviated"):
                sw = note.get("swing", 0.0)
                tag = f"off-model ({'+' if sw > 0 else ''}{sw:g} to you)" if sw else "off-model"
            else:
                tag = "as modelled"
        print(f"  {ply:>3} {who:4} {played:>22}  {rec_s:>22}  {tag}")
    fn, fo = v["followed"]
    print(f"\n  you followed the recommendation on {fn}/{fo} of your turns; "
          f"the NPC went off-model {v['npc_dev']} time(s)"
          + (f", costing you {abs(v['npc_cost']):g}" if v["npc_cost"] else ""))
    return 0


def cmd_summary(games) -> int:
    if not games:
        print("no games logged yet")
        return 0
    hits = offs = unknown = 0
    fn = fo = dev = 0
    cost = 0.0
    for g in games:
        v = _verdict(g)
        if v["predicted"] is None:
            unknown += 1
        elif _hit(v["predicted"], v["actual"]) == "match":
            hits += 1
        else:
            offs += 1
        fn += v["followed"][0]
        fo += v["followed"][1]
        dev += v["npc_dev"]
        cost += v["npc_cost"]
    print(f"{len(games)} games logged")
    print(f"  opening prediction:  {hits} matched the result, {offs} off"
          + (f", {unknown} unresolved" if unknown else ""))
    print(f"  your moves:          {fn}/{fo} followed the recommendation")
    print(f"  NPC vs model:        went off-model {dev} time(s)"
          + (f"; net {abs(cost):g} worse for you than the model predicted" if cost else
             "; never in a way that cost you"))
    if offs:
        print("\n  off predictions:")
        for i, g in enumerate(games, 1):
            v = _verdict(g)
            if v["predicted"] is not None and _hit(v["predicted"], v["actual"]) == "OFF":
                print(f"    #{i}  {g['npc']}: predicted {_pred_txt(v['predicted'])}, "
                      f"got {v['actual']:+d}  (review {i} for the divergence)")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("game", nargs="?", type=int, help="replay this game number")
    p.add_argument("--summary", action="store_true", help="aggregate over all games")
    p.add_argument("--npc", help="filter the list to NPCs matching this")
    args = p.parse_args(argv)

    games = _load()
    try:
        if args.game is not None:
            return cmd_show(games, args.game)      # one game - no need to warm everything
        warm_cache(games)
        if args.summary:
            return cmd_summary(games)
        return cmd_list(games, args)
    finally:
        _save_vcache()


if __name__ == "__main__":
    raise SystemExit(main())
