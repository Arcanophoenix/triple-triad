"""Capture-resolution tests.  Board cells::

    0 1 2
    3 4 5
    6 7 8

Side order is (N, E, S, W).  Placing at centre cell 4: the card's N meets cell
1's S, its E meets cell 5's W, its S meets cell 7's N, its W meets cell 3's E.
"""
import pytest

from helpers import owners, place
from tt.data import register_test_card as C
from tt.model import GameState, RuleSet, is_terminal, score_a, value_a

PLAIN = RuleSet()


def test_basic_capture_and_survival():
    atk = C((9, 2, 1, 1))
    north = C((1, 1, 5, 1))   # S side 5  -> beaten by atk N 9
    east = C((1, 1, 1, 9))    # W side 9  -> survives atk E 2
    b, log = place(PLAIN, {1: (north, 1), 5: (east, 1)}, 4, atk, 0)
    assert owners(b)[1] == 0
    assert owners(b)[5] == 1
    assert log["basic"] == [1]


def test_reverse_inverts_comparison():
    atk = C((9, 2, 1, 1))
    north = C((1, 1, 5, 1))
    east = C((1, 1, 1, 9))
    b, _ = place(RuleSet(reverse=True), {1: (north, 1), 5: (east, 1)}, 4, atk, 0)
    assert owners(b)[1] == 1   # 9 no longer beats 5
    assert owners(b)[5] == 0   # 2 now beats 9


def test_corner_placement_has_two_neighbours():
    atk = C((1, 9, 1, 1))          # placed at cell 0: E -> cell 1, S -> cell 3
    east = C((1, 1, 1, 2))         # W side 2 -> beaten
    south = C((9, 1, 1, 1))        # N side 9 -> survives atk S 1
    b, _ = place(PLAIN, {1: (east, 1), 3: (south, 1)}, 0, atk, 0)
    assert owners(b)[1] == 0
    assert owners(b)[3] == 1


def test_same_captures_regardless_of_value():
    atk = C((5, 5, 1, 1))
    north = C((1, 1, 5, 1))   # S 5 == atk N 5
    east = C((1, 1, 1, 5))    # W 5 == atk E 5
    b, log = place(RuleSet(same=True), {1: (north, 1), 5: (east, 1)}, 4, atk, 0)
    assert owners(b)[1] == 0 and owners(b)[5] == 0
    assert log["same"] == [1, 5]
    assert log["basic"] == []


def test_same_needs_at_least_one_enemy_among_matches():
    atk = C((5, 5, 1, 1))
    ally = C((1, 1, 5, 1))    # friendly match
    enemy = C((1, 1, 1, 5))   # enemy match
    b, log = place(RuleSet(same=True), {1: (ally, 0), 5: (enemy, 1)}, 4, atk, 0)
    assert log["same"] == [5]          # only the enemy is flipped / reported
    assert owners(b)[5] == 0


def test_same_single_match_does_not_trigger():
    atk = C((5, 1, 1, 1))
    north = C((1, 1, 5, 1))
    b, log = place(RuleSet(same=True), {1: (north, 1)}, 4, atk, 0)
    assert log["same"] == []
    assert owners(b)[1] == 1


def test_same_wall_counts_board_edges_as_A():
    # placed at corner 0: N and W face walls; E -> cell 1
    atk = C((10, 3, 1, 10))            # N=A, W=A (both wall matches), E=3
    east = C((1, 1, 1, 3))            # W 3 == atk E 3 (card match, equal value)
    with_wall = RuleSet(same=True, same_wall=True)
    b, log = place(with_wall, {1: (east, 1)}, 0, atk, 0)
    assert owners(b)[1] == 0
    assert log["same"] == [1]
    b2, log2 = place(RuleSet(same=True), {1: (east, 1)}, 0, atk, 0)
    assert owners(b2)[1] == 1          # only one hit without the walls


def test_plus_captures_on_equal_sums():
    atk = C((2, 3, 1, 1))
    north = C((1, 1, 4, 1))   # 2 + 4 == 6
    east = C((1, 1, 1, 3))    # 3 + 3 == 6
    b, log = place(RuleSet(plus=True), {1: (north, 1), 5: (east, 1)}, 4, atk, 0)
    assert owners(b)[1] == 0 and owners(b)[5] == 0
    assert log["plus"] == [1, 5]


def test_plus_no_capture_when_sums_differ():
    atk = C((2, 3, 1, 1))
    north = C((1, 1, 4, 1))   # sum 6
    east = C((1, 1, 1, 5))    # sum 8
    b, log = place(RuleSet(plus=True), {1: (north, 1), 5: (east, 1)}, 4, atk, 0)
    assert log["plus"] == []
    assert owners(b)[1] == 1 and owners(b)[5] == 1


def test_combo_cascades_from_a_same_flip():
    atk = C((5, 1, 1, 1))            # N matches cell1 S, W matches cell3 E
    north = C((1, 9, 5, 1))          # S 5 (Same), then E 9 beats cell2
    west = C((1, 1, 1, 1))           # E 1 == atk W 1 (Same)
    far = C((1, 1, 1, 2))            # cell2: W 2, falls to cell1's combo
    b, log = place(RuleSet(same=True), {1: (north, 1), 3: (west, 1), 2: (far, 1)}, 4, atk, 0)
    assert sorted(log["same"]) == [1, 3]
    assert log["combo"] == [2]
    assert owners(b)[2] == 0


def test_plain_capture_does_not_combo():
    atk = C((9, 1, 1, 1))            # N 9 beats cell1 by the ordinary rule
    north = C((1, 9, 1, 1))          # would beat cell2 if it comboed
    far = C((1, 1, 1, 2))
    b, log = place(PLAIN, {1: (north, 1), 2: (far, 1)}, 4, atk, 0)
    assert log["basic"] == [1]
    assert log["combo"] == []
    assert owners(b)[2] == 1


def test_ascension_boosts_sides_by_type_count():
    prim_a = C((5, 1, 1, 1), kind="Primal")
    filler1 = C((1, 1, 1, 1), kind="Primal")
    filler2 = C((1, 1, 1, 1), kind="Primal")
    target = C((1, 1, 6, 1), kind="None")   # S 6
    layout = {3: (filler1, 0), 5: (filler2, 0), 1: (target, 1)}
    # 3 Primals on the board -> +2 to the placed Primal's sides: N 5 -> 7 > 6
    b, _ = place(RuleSet(ascension=True), layout, 4, prim_a, 0)
    assert owners(b)[1] == 0
    b2, _ = place(PLAIN, layout, 4, prim_a, 0)
    assert owners(b2)[1] == 1


def test_ascension_delta_is_the_faction_count_and_caps_at_ten():
    from tt.rules import eff
    prim = C((2, 1, 1, 9), kind="Primal")
    f1 = C((1, 1, 1, 1), kind="Primal")
    f2 = C((1, 1, 1, 1), kind="Primal")
    b = ((None,) * 9)
    b = list(b)
    b[4], b[3], b[5] = (prim.id, 0), (f1.id, 0), (f2.id, 0)   # 3 Primals on the board
    b = tuple(b)
    assert eff(RuleSet(ascension=True), b, 4, 0) == 5     # 2 + 3
    assert eff(RuleSet(ascension=True), b, 4, 3) == 10    # 9 + 3 -> capped at A
    assert eff(RuleSet(descension=True), b, 4, 0) == 1    # max(1, 2 - 3)


def test_fallen_ace_one_beats_ace():
    atk = C((1, 1, 1, 1))            # N printed 1
    ace = C((1, 1, 10, 1))           # S printed A
    b, _ = place(RuleSet(fallen_ace=True), {1: (ace, 1)}, 4, atk, 0)
    assert owners(b)[1] == 0
    b2, _ = place(PLAIN, {1: (ace, 1)}, 4, atk, 0)
    assert owners(b2)[1] == 1
    b3, _ = place(RuleSet(fallen_ace=True, reverse=True), {1: (ace, 1)}, 4, atk, 0)
    assert owners(b3)[1] == 1        # Reverse cancels Fallen Ace on this pairing


def test_ace_beats_one_normally():
    atk = C((10, 1, 1, 1))           # N printed A
    one = C((1, 1, 1, 1))            # S printed 1
    b, _ = place(PLAIN, {1: (one, 1)}, 4, atk, 0)
    assert owners(b)[1] == 0
    # DISPUTED: under Fallen Ace "hard" mode a placed A does NOT capture a 1.
    b2, _ = place(RuleSet(fallen_ace=True), {1: (one, 1)}, 4, atk, 0)
    assert owners(b2)[1] == 1


def test_terminal_scoring_counts_the_unplayed_hand_card():
    a = C((1, 1, 1, 1))
    full = tuple((a.id, 0) if i < 6 else (a.id, 1) for i in range(9))
    st = GameState(full, ((), ()), 0, PLAIN)
    assert is_terminal(st)
    assert score_a(st) == 6 and value_a(st) == 2

    mixed = tuple((a.id, 0) if i < 5 else (a.id, 1) for i in range(9))
    st_a = GameState(mixed, ((a.id,), ()), 0, PLAIN)   # A holds the last card
    assert score_a(st_a) == 6
    st_b = GameState(mixed, ((), (a.id,)), 1, PLAIN)   # B holds the last card
    assert score_a(st_b) == 5 and value_a(st_b) == 0    # 5-5 draw
