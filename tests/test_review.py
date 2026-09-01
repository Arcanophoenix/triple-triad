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


def _chaos_game() -> dict:
    """A full Chaos match where both sides always played the best CELL for the card
    they were dealt.  The deal is the random part of Chaos, so it is stubbed with
    "hand index 0" - deterministic, and irrelevant to what review checks, which is
    only ever whether the *cell* was the best one for the card that arrived.

    The NPC leads so all five of its cards get played, which keeps the fixture
    independent of what decks.json records for the NPC.
    """
    from tt.data import find_npc, npc_deck_options, is_variable_deck
    npc = find_npc("Swift")                      # match rules: Chaos
    e = load_decks()[npc["name"]]
    npc5 = [resolve(x).id for x in (npc_deck_options(e)[0] if is_variable_deck(e)
                                    else e["cards"])]
    you = [resolve(x).id for x in load_collection()["decks"]["starter"]]
    rules = RuleSet.from_names(e.get("rules") or npc["rules"])
    assert rules.chaos
    st = GameState(EMPTY_BOARD, (tuple(you), tuple(npc5)), 1, rules)
    moves = []
    while not is_terminal(st):
        dealt = 0                                 # stand-in for the random deal
        _hi, cell, _v, _ranked = R._chaos_rank(st, dealt, "greedy")
        moves.append([st.to_move, st.hands[st.to_move][dealt], cell])
        st = apply(st, dealt, cell)
    score_you = sum(1 for s in st.board if s and s[1] == 0) + len(st.hands[0])
    return {"npc": npc["name"], "rules": rules.names(), "deck": you,
            "youFirst": False, "opp": "greedy", "moves": moves,
            "revealed": [], "scoreYou": score_you}


@pytest.mark.slow
def test_chaos_games_are_reviewed_instead_of_skipped():
    """analyze() cannot rank moves you do not choose, so review used to catch the
    ValueError and return no verdict at all: no prediction, and `followed` stuck
    at 0/0 - a Chaos game looked reviewed but nothing had been checked.  It now
    replays against the card the log says was dealt.
    """
    g = _chaos_game()
    v = R._verdict_compute(g)
    assert v["error"] is None
    assert v["predicted"] is not None            # used to be None for every Chaos game
    assert v["approx"] is True                   # ...and is honest that it is an estimate

    fn, fo = v["followed"]
    assert fo > 0                                # your turns were actually checked
    assert fn == fo                              # each played the best cell for its card
    assert v["npc_dev"] == 0                     # NPC ran the model review re-solves with


def test_non_chaos_verdicts_are_not_flagged_approximate():
    assert R._verdict_compute(_master_game(True))["approx"] is False
