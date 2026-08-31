import pytest
from helpers import build

from tt.data import register_test_card as C
from tt.model import EMPTY_BOARD, GameState, RuleSet, value_a
from tt.solver import analyze, apply, legal_moves, new_match, npc_move

PLAIN = RuleSet()
F = C((1, 1, 1, 1))          # inert filler


def test_forced_last_move_is_scored_exactly():
    strong = C((9, 1, 1, 9))                       # placed at cell 8: N->5, W->7
    base = {i: (F, i % 2) for i in range(8)}       # 4 each; cells 5 and 7 are B's
    st = GameState(build(base), ((strong.id,), ()), 0, PLAIN)
    a = analyze(st)
    assert a.best.cell == 8
    assert a.best.value == 4                       # A flips cells 5 and 7 -> 7 vs 3
    assert a.outcome == "win" and a.margin == 4


def test_minimax_avoids_a_greedy_trap():
    # A has one card; placing it greedily (cell 7, captures 1) lets B swing two
    # back for -4, while the quiet cell 8 (captures 0) only loses by 2.
    P = C((9, 1, 1, 1))
    R = C((9, 1, 1, 9))
    base = {0: (F, 0), 1: (F, 0), 2: (F, 1), 3: (F, 1), 4: (F, 1), 5: (F, 0), 6: (F, 1)}
    st = GameState(build(base), ((P.id,), (R.id,)), 0, PLAIN)
    a = analyze(st)
    assert a.best.cell == 8 and a.best.value == -2
    worst = a.ranked[-1]
    assert worst.cell == 7 and worst.value == -4


def test_pv_reaches_a_terminal_that_matches_the_backed_up_value():
    strong = C((8, 8, 2, 3))
    deckA = (F.id, F.id, strong.id, F.id, F.id)
    deckB = (F.id, strong.id, F.id, F.id, F.id)
    base = {0: (F, 0), 1: (F, 1), 2: (F, 0), 3: (F, 1), 4: (F, 0)}
    st = GameState(build(base), ((deckA[0], deckA[1]), deckB[:3]), 0, PLAIN)
    a = analyze(st)
    assert len(a.pv) == 4
    cur = st
    for _mv, nxt in a.pv:
        cur = nxt
    assert all(s is not None for s in cur.board)
    assert value_a(cur) == a.best.value
    assert -10 <= a.best.value <= 10


def test_opening_board_is_reduced_by_symmetry():
    st = GameState(EMPTY_BOARD, ((F.id,) * 5, (F.id,) * 5), 0, PLAIN)
    cells = {c for _hi, c in legal_moves(st)}
    assert cells == {0, 1, 4}


def test_order_rule_forces_the_first_hand_card():
    a1, a2, a3 = C((5, 5, 5, 5)), C((6, 6, 6, 6)), C((7, 7, 7, 7))
    st = GameState(EMPTY_BOARD, ((a1.id, a2.id, a3.id, F.id, F.id), (F.id,) * 5),
                   0, RuleSet(order=True))
    assert {hi for hi, _c in legal_moves(st)} == {0}


def test_new_match_requires_a_recorded_deck():
    import pytest
    with pytest.raises(ValueError):
        new_match("Aiglephine", ["Dodo"] * 5, npc_deck=None)


def test_variable_deck_options_are_the_pool_combinations():
    from tt.data import deck_draw, is_variable_deck, npc_deck_options
    fixed = {"cards": ["A", "B", "C", "D", "E"], "rules": ["Plus"]}
    var = {"fixed": ["A", "B", "C"], "pool": ["W", "X", "Y", "Z"], "draw": 2}
    assert not is_variable_deck(fixed) and deck_draw(fixed) == 0
    assert is_variable_deck(var) and deck_draw(var) == 2
    assert npc_deck_options(fixed) == [["A", "B", "C", "D", "E"]]
    opts = npc_deck_options(var)
    assert len(opts) == 6                       # C(4, 2)
    assert all(o[:3] == ["A", "B", "C"] and len(o) == 5 for o in opts)
    assert ["A", "B", "C", "W", "X"] in opts and ["A", "B", "C", "Y", "Z"] in opts
    # draw defaults to 5 - len(fixed) when omitted
    assert deck_draw({"fixed": ["A", "B", "C", "D"], "pool": ["Y", "Z"]}) == 1


def test_new_match_variable_deck_asks_for_the_draw():
    import pytest
    with pytest.raises(ValueError, match="draws"):
        new_match("Jonas of the Three Spades", ["Dodo"] * 5, npc_deck=None)


def test_starter_collection_is_always_present():
    from tt.data import STARTER_CARDS, load_collection, resolve
    col = load_collection()
    assert col["decks"]["starter"] == STARTER_CARDS
    assert set(STARTER_CARDS) <= set(col["owned"])
    assert [resolve(n).stars for n in STARTER_CARDS] == [1, 1, 1, 1, 1]


def test_npc_move_grabs_the_most_captures():
    # B to move: P at centre flips two A cards; anywhere else flips none
    P = C((9, 1, 1, 9))
    Q = C((1, 1, 1, 1))
    base = {0: (F, 0), 1: (F, 0), 2: (F, 0), 3: (F, 0)}  # 1 and 3 border the centre
    st = GameState(build(base), ((F.id,), (P.id, Q.id)), 1, PLAIN)
    assert npc_move(st) == (0, 4)


def test_greedy_opponent_is_never_better_for_it_than_optimal():
    P = C((9, 1, 1, 1))
    R = C((9, 1, 1, 9))
    base = {0: (F, 1), 1: (F, 1), 2: (F, 0), 3: (F, 0), 4: (F, 0), 5: (F, 1), 6: (F, 0)}
    st = GameState(build(base), ((R.id,), (P.id, F.id)), 1, PLAIN)   # B (NPC) to move
    opt = analyze(st, opp="optimal").best.value
    grd = analyze(st, opp="greedy").best.value
    assert grd > opt          # the greedy NPC takes the bait; optimal would not


def test_greedy_opponent_opening_is_fast_and_bounded():
    hi = C((9, 9, 9, 9))
    lo = C((2, 2, 2, 2))
    deck = (hi.id, lo.id, lo.id, lo.id, lo.id)
    st = GameState(EMPTY_BOARD, (deck, deck), 0, PLAIN)
    v = analyze(st, opp="greedy").best.value
    assert -10 <= v <= 10


@pytest.mark.slow
def test_full_opening_solve_is_deterministic():
    hi = C((9, 9, 9, 9))
    lo = C((2, 2, 2, 2))
    deckA = (hi.id, lo.id, lo.id, lo.id, lo.id)
    deckB = (hi.id, lo.id, lo.id, lo.id, lo.id)
    st = GameState(EMPTY_BOARD, (deckA, deckB), 0, PLAIN)
    v1 = analyze(st).best.value
    v2 = analyze(st).best.value
    assert v1 == v2
    assert -10 <= v1 <= 10
