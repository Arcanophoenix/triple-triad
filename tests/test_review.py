import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import review as R  # noqa: E402
from tt.data import load_collection, load_decks, resolve  # noqa: E402
from tt.model import EMPTY_BOARD, GameState, RuleSet, is_terminal  # noqa: E402
from tt.solver import analyze, apply  # noqa: E402


def _master_game(you_first: bool) -> dict:
    """A full match vs the (fixed-deck) Triple Triad Master with both sides driven
    by the greedy model - so review's re-solve must agree with it exactly."""
    d = load_decks()["Triple Triad Master"]
    npc5 = [resolve(x).id for x in d["cards"]]
    you = [resolve(x).id for x in load_collection()["decks"]["starter"]]
    rules = RuleSet.from_names(d.get("rules") or [])
    st = GameState(EMPTY_BOARD, (tuple(you), tuple(npc5)), 0 if you_first else 1, rules)
    moves = []
    while not is_terminal(st):
        a = analyze(st, opp="greedy")
        hi, ce = a.best.hand_idx, a.best.cell
        moves.append([st.to_move, st.hands[st.to_move][hi], ce])
        st = apply(st, hi, ce)
    score_you = sum(1 for s in st.board if s and s[1] == 0) + len(st.hands[0])
    return {"npc": "Triple Triad Master", "rules": rules.names(), "deck": you,
            "youFirst": you_first, "opp": "greedy", "moves": moves,
            "revealed": [], "scoreYou": score_you}


def test_verdict_matches_a_self_consistent_game():
    v = R._verdict(_master_game(True))
    assert v["error"] is None
    lo, hi = v["predicted"]
    assert lo <= v["actual"] <= hi
    assert R._hit(v["predicted"], v["actual"]) == "match"
    fn, fo = v["followed"]
    assert fo > 0 and fn == fo                 # every move was the recommended one
    assert v["npc_dev"] == 0                   # NPC ran the model review re-solves with


def test_npc_completions_fill_from_the_recorded_deck_when_a_card_stays_hidden():
    g = _master_game(True)                     # you lead -> NPC plays 4, holds 1
    comps = R._npc_completions(g)
    assert len(comps) == 1
    assert sorted(comps[0]) == sorted(resolve(x).id for x in
                                      load_decks()["Triple Triad Master"]["cards"])


def test_flags_a_turn_that_ignored_the_recommendation():
    g = _master_game(True)
    d = load_decks()["Triple Triad Master"]
    npc5 = [resolve(x).id for x in d["cards"]]
    you = g["deck"]
    rules = RuleSet.from_names(d.get("rules") or [])
    st = GameState(EMPTY_BOARD, (tuple(you), tuple(npc5)), 0, rules)
    prefix = []
    for side, card, cell in g["moves"]:
        if side == 0:
            a = analyze(st, opp="greedy")
            alt = next((r for r in a.ranked if r.value != a.ranked[0].value), None)
            if alt is not None:
                bad = [0, st.hands[0][alt.hand_idx], alt.cell]
                rec = {**g, "moves": prefix + [bad], "scoreYou": 5}
                v = R._verdict(rec)
                fn, fo = v["followed"]
                assert fo >= 1 and fn < fo     # the diverging turn is counted as not-followed
                return
        prefix.append([side, card, cell])
        st = apply(st, st.hands[side].index(card), cell)
    pytest.skip("no value-differing alternative move in this matchup")
