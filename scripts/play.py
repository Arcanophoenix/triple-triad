#!/usr/bin/env python3
"""Play a match turn by turn with a recommendation each of your turns.

  scripts/play.py "Aiglephine" --deck starter --second

Set the match up once, then each turn just say what happened:
  - your turn  : press Enter to take the recommended move, or type "<card> <cell>"
  - NPC's turn : type "<card> <cell>" (cells are 1-9, row-major)
Commands: u/undo, b/board, q/quit.

If the NPC's deck isn't recorded you'll be asked for their 5 cards (and offered
to save them), so playing a new NPC through this tool fills in data/decks.json.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tt.data import (  # noqa: E402
    CARDS, deck_draw, find_npc, is_variable_deck, load_decks, resolve, save_decks,
)
from tt.format import render_board  # noqa: E402
from tt.model import EMPTY_BOARD, GameState, RuleSet, is_terminal, score_a  # noqa: E402
from tt.regions import effective_rules  # noqa: E402
from tt.solver import analyze, apply  # noqa: E402


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        raise SystemExit(0)


def _expand(spec: str) -> list[str]:
    from tt.data import load_collection
    if spec and "," not in spec:
        named = load_collection()["decks"].get(spec.strip())
        if named:
            return list(named)
    return [s.strip() for s in spec.split(",") if s.strip()]


def _parse_move(line: str, state: GameState):
    """'Coeurl 3' / '3 coeurl' -> (hand_idx, cell0) for the side to move."""
    toks = line.split()
    cells = [t for t in toks if t.isdigit()]
    if not cells:
        raise ValueError("need a cell number 1-9")
    cell = int(cells[0])
    if not 1 <= cell <= 9:
        raise ValueError("cell must be 1-9")
    if state.board[cell - 1] is not None:
        raise ValueError(f"cell {cell} is already taken")
    name = " ".join(t for t in toks if not t.isdigit())
    if not name:
        raise ValueError("need a card name")
    cid = resolve(name).id
    hand = state.hands[state.to_move]
    if cid not in hand:
        who = "your" if state.to_move == 0 else "the NPC's"
        raise ValueError(f"{CARDS[cid].name} isn't in {who} hand")
    return hand.index(cid), cell - 1


def _hand(state: GameState, side: int) -> str:
    return "  ".join(CARDS[c].name.removesuffix(" Card") for c in state.hands[side]) or "(empty)"


def _show(state: GameState) -> None:
    on_a = sum(1 for s in state.board if s and s[1] == 0) + len(state.hands[0])
    print()
    print(render_board(state.board))
    print(f"\n  you {on_a} - {10 - on_a} npc")
    print(f"  your hand: {_hand(state, 0)}")
    print(f"  npc hand : {_hand(state, 1)}")


def _recommend(state: GameState, opp: str) -> tuple:
    a = analyze(state, opp=opp)
    b = a.best
    verdict = f"{a.outcome.upper()} by {abs(a.margin):g}"
    alts = [r for r in a.ranked[1:3]]
    line = f"  >>> {CARDS[state.hands[0][b.hand_idx]].name} at cell {b.cell + 1}  ({verdict})"
    if alts:
        extra = ", ".join(f"{r.card.name.removesuffix(' Card')}@{r.cell + 1} "
                          f"{(r.value if state.to_move == 0 else -r.value):+g}" for r in alts)
        line += f"\n      alts: {extra}"
    return (b.hand_idx, b.cell), line


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("npc")
    p.add_argument("--deck", required=True, help="your 5 cards, comma-separated or a name")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--first", action="store_true", help="you take turn 1")
    g.add_argument("--second", action="store_true", help="the NPC takes turn 1")
    p.add_argument("--rules", default=None, help="override the full rule list (regional included)")
    p.add_argument("--no-regional", action="store_true",
                   help="use the NPC's match rules only, skip recorded regional rules")
    p.add_argument("--opp", choices=("greedy", "optimal"), default="greedy",
                   help="NPC model (default greedy: realistic + fast)")
    args = p.parse_args(argv)

    try:
        npc = find_npc(args.npc)
    except KeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    decks = load_decks()
    entry = decks.get(npc["name"], {})

    npc_cards = entry.get("cards")
    if not npc_cards:
        if is_variable_deck(entry):
            print(f"{npc['name']} always plays {', '.join(entry['fixed'])} and draws "
                  f"{deck_draw(entry)} of [{', '.join(entry['pool'])}].")
            prompt = f"Enter their 5 cards (the {deck_draw(entry)} they drew + the fixed ones): "
        else:
            prompt = f"No deck recorded for {npc['name']}. Enter their 5 cards: "
        raw = _ask(prompt).strip()
        try:
            cards = [resolve(x).name for x in raw.split(",") if x.strip()]
        except KeyError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if len(cards) != 5:
            print("error: need exactly 5 cards", file=sys.stderr)
            return 1
        npc_cards = cards
        if not is_variable_deck(entry) and \
                _ask("save this deck for next time? [y/N]: ").strip().lower().startswith("y"):
            decks[npc["name"]] = {"cards": npc_cards}
            save_decks(decks)
            print(f"saved to data/decks.json")

    rnames = effective_rules(npc, deck_entry=entry, override=args.rules,
                             use_regional=not args.no_regional and not args.rules)
    rules = RuleSet.from_names([r.strip() for r in rnames if r.strip()])

    try:
        you = tuple(resolve(x).id for x in _expand(args.deck))
        them = tuple(resolve(x).id for x in npc_cards)
    except KeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if len(you) != 5 or len(them) != 5:
        print("error: each deck needs exactly 5 cards", file=sys.stderr)
        return 1

    if args.first:
        first = 0
    elif args.second:
        first = 1
    else:
        first = 0 if _ask("do you go first? [Y/n]: ").strip().lower() != "n" else 1

    print(f"\n{npc['name']} — rules: {', '.join(rules.names()) or '(none)'}   "
          f"opp model: {args.opp}")
    if rules.chaos or rules.roulette or rules.swap:
        print("note: Chaos / Roulette / Swap aren't handled here - use solve.py move.")

    history = [GameState(EMPTY_BOARD, (you, them), first, rules)]

    while not is_terminal(history[-1]):
        state = history[-1]
        _show(state)
        yours = state.to_move == 0
        default = None
        if yours:
            try:
                default, rec = _recommend(state, args.opp)
                print("\n" + rec)
                prompt = "  your move [Enter = take it]: "
            except Exception as e:  # noqa: BLE001
                print(f"  (no recommendation: {e})")
                prompt = "  your move <card cell>: "
        else:
            prompt = "  NPC played <card cell>: "

        try:
            raw = input(prompt).strip()
        except EOFError:
            print()
            return 0
        low = raw.lower()
        if low in ("q", "quit"):
            return 0
        if low in ("b", "board"):
            continue
        if low in ("u", "undo"):
            if len(history) > 1:
                history.pop()
            continue
        try:
            mv = default if (yours and not raw) else _parse_move(raw, state)
            if mv is None:
                raise ValueError("type '<card> <cell>'")
            history.append(apply(state, *mv))
        except (ValueError, KeyError) as e:
            print(f"  ! {e}")

    final = history[-1]
    _show(final)
    s = score_a(final)
    print(f"\n  FINAL: {'WIN' if s > 5 else 'LOSS' if s < 5 else 'DRAW'}  {s} - {10 - s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
