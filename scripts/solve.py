#!/usr/bin/env python3
"""Next-best-move and pre-game analysis for a Triple Triad match.

  # mid-game: give the board and both remaining hands, ask for your best move
  scripts/solve.py move \
      --board "Ifrit@A, ., Garuda@B, ., Titan@A, ., ., ., ." \
      --you "Ramuh, Shiva" --npc "Odin, Bahamut, Leviathan" \
      --npc-name "Arsieu"                # pulls that NPC's rules

  # pre-game: play the whole match out optimally from an empty board
  scripts/solve.py plan "Arsieu" --deck "Ramuh,Shiva,Odin,Ifrit,Titan" --second

Cells are numbered 1..9, row-major.  Card names are loose (case-insensitive,
"Card" optional, & / and interchangeable, bare number works).
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tt.data import CARDS, find_npc, load_collection, load_decks, resolve  # noqa: E402
from tt.format import parse_board, parse_deck, render_board, render_hand  # noqa: E402
from tt.model import EMPTY_BOARD, GameState, RuleSet  # noqa: E402
from tt.regions import effective_rules  # noqa: E402
from tt.solver import analyze, new_match  # noqa: E402


def _cell_label(c: int) -> str:
    return f"cell {c + 1} (r{c // 3 + 1} c{c % 3 + 1})"


def _expand_deck(spec: str) -> str:
    """Expand a bare named deck ('starter', or any key in collection.json's
    'decks') to its comma-separated card list; pass anything else through."""
    if spec and "," not in spec:
        named = load_collection()["decks"].get(spec.strip())
        if named:
            return ",".join(named)
    return spec


def _rules_for(args) -> RuleSet:
    if args.rules is not None:
        return RuleSet.from_names([x for x in args.rules.split(",") if x.strip()])
    if getattr(args, "npc_name", None):
        npc = find_npc(args.npc_name)
        entry = load_decks().get(npc["name"], {})
        names = effective_rules(npc, deck_entry=entry,
                                use_regional=not getattr(args, "no_regional", False))
        return RuleSet.from_names(names)
    return RuleSet()


def _verdict(v: float) -> str:
    # v is always from your (player A) perspective
    return f"{'WIN' if v > 0 else 'LOSS' if v < 0 else 'DRAW'} by {abs(v):g}"


def _print_analysis(state: GameState, forced_idx=None, opp="optimal") -> None:
    who = "you" if state.to_move == 0 else "NPC"
    a = analyze(state, forced_hand_idx=forced_idx, opp=opp)
    print(f"\nrules : {', '.join(state.rules.names()) or '(none)'}   opp: {opp}")
    print(render_board(state.board))
    print(render_hand(state.hands[0], "\nyour hand"))
    print(render_hand(state.hands[1], "npc hand "))
    print(f"\nto move: {who}   (searched {a.tt_size} positions)")
    verb = "play" if state.to_move == 0 else "expect NPC to play"
    print(f"\nbest: {verb} {a.best.card.name} [{a.best.card.high}] at {_cell_label(a.best.cell)}"
          f"  ->  {_verdict(a.best.value)} (your result)")
    hdr = "your moves, best first" if state.to_move == 0 else "NPC's options (your result)"
    print(f"\n{hdr}:")
    for r in a.ranked:
        print(f"  {r.card.name:<26} @ {_cell_label(r.cell):<20} {r.value:+g}  "
              f"{'win' if r.value > 0 else 'loss' if r.value < 0 else 'draw'}")
    if a.pv:
        print("\noptimal line:")
        for mv, nxt in a.pv:
            actor = "you" if nxt.to_move == 1 else "npc"
            print(f"  {actor:>3}: {mv.card.name} @ {_cell_label(mv.cell)}")


def _resolve_inputs(fn):
    try:
        return fn(), None
    except (KeyError, ValueError) as e:
        return None, str(e)


def cmd_move(args) -> int:
    board, err = _resolve_inputs(lambda: parse_board(args.board))
    you, e2 = _resolve_inputs(lambda: tuple(parse_deck(_expand_deck(args.you))) if args.you else ())
    npc, e3 = _resolve_inputs(lambda: tuple(parse_deck(args.npc)) if args.npc else ())
    for e in (err, e2, e3):
        if e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    to_move = 0 if args.turn == "you" else 1
    try:
        rules = _rules_for(args)
    except (KeyError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    placed = sum(1 for s in board if s is not None)
    total = placed + len(you) + len(npc)
    if total != 10:
        print(f"warning: {placed} on board + {len(you)} your + {len(npc)} npc = {total}"
              f" cards (a match has 10); check the inputs", file=sys.stderr)
    state = GameState(board, (you, npc), to_move, rules)
    forced = None
    if rules.chaos:
        if not args.card:
            print("error: Chaos is active - pass --card <the card you were dealt>", file=sys.stderr)
            return 1
        cid = resolve(args.card).id
        if cid not in you:
            print("error: --card must be one of your hand cards", file=sys.stderr)
            return 1
        forced = you.index(cid)
    _print_analysis(state, forced, opp=args.opp)
    return 0


def cmd_plan(args) -> int:
    deck = [s.strip() for s in _expand_deck(args.deck).split(",") if s.strip()]
    npc_deck = [s.strip() for s in args.npc_deck.split(",")] if args.npc_deck else None
    rules = [s.strip() for s in args.rules.split(",")] if args.rules else None
    try:
        state = new_match(args.npc, deck, you_first=not args.second,
                          npc_deck=npc_deck, rules=rules)
    except (KeyError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"{args.npc}: you go {'second' if args.second else 'first'}")
    _print_analysis(state, opp=args.opp)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("move", help="best move for a mid-game position")
    m.add_argument("--board", required=True, help="9 cells: '<card>@A' / '<card>@B' / '.'")
    m.add_argument("--you", default="", help="your remaining hand, comma-separated")
    m.add_argument("--npc", default="", help="npc remaining hand, comma-separated")
    m.add_argument("--turn", choices=("you", "npc"), default="you")
    m.add_argument("--rules", default=None, help="comma-separated rule names")
    m.add_argument("--npc-name", default=None, help="look up rules from this NPC")
    m.add_argument("--no-regional", action="store_true",
                   help="with --npc-name: match rules only, skip recorded regional rules")
    m.add_argument("--card", default=None, help="under Chaos: the card you were dealt")
    m.add_argument("--opp", choices=("optimal", "greedy"), default="optimal",
                   help="NPC model: optimal minimax (safe) or greedy (realistic, exploitable)")
    m.set_defaults(fn=cmd_move)

    pl = sub.add_parser("plan", help="solve a whole match from an empty board")
    pl.add_argument("npc")
    pl.add_argument("--deck", required=True, help="your 5 cards, comma-separated")
    pl.add_argument("--second", action="store_true", help="you play second")
    pl.add_argument("--npc-deck", default=None, help="override the recorded npc deck")
    pl.add_argument("--rules", default=None, help="override the rules")
    pl.add_argument("--opp", choices=("optimal", "greedy"), default="optimal",
                   help="NPC model: optimal minimax (safe) or greedy (realistic, exploitable)")
    pl.set_defaults(fn=cmd_plan)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
