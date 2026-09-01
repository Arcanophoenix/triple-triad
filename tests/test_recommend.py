from math import comb

import pytest

from tt.data import register_test_card as C
from tt.model import RuleSet
from tt.recommend import (
    HIGH_RARITY, card_score, greedy_playout, legal_decks, recommend,
)
from tt.model import EMPTY_BOARD, GameState

PLAIN = RuleSet()


def _weak(sides, stars=1):
    c = C(sides)
    object.__setattr__(c, "stars", stars)   # Card is frozen; tweak for the test
    return c


def test_legal_decks_respect_the_high_rarity_limit():
    lows = [_weak((2, 2, 2, 2)).id for _ in range(4)]
    highs = [_weak((9, 9, 9, 9), stars=HIGH_RARITY).id for _ in range(3)]
    from tt.data import CARDS
    for deck in legal_decks(lows + highs):
        assert len(deck) == 5
        assert sum(CARDS[i].stars >= HIGH_RARITY for i in deck) <= 1


def test_card_score_inverts_under_reverse():
    strong = C((9, 9, 9, 8))
    weak = C((2, 1, 2, 1))
    assert card_score(strong, PLAIN) > card_score(weak, PLAIN)
    assert card_score(weak, RuleSet(reverse=True)) > card_score(strong, RuleSet(reverse=True))


def test_card_score_under_fallen_ace_keeps_high_is_good():
    fa = RuleSet(fallen_ace=True)
    strong = C((9, 9, 9, 8))
    weak = C((2, 1, 2, 1))
    # Fallen Ace alone must NOT flip to "low is good" the way Reverse does
    assert card_score(strong, fa) > card_score(weak, fa)
    # ...but a card carrying a 1 (can capture an A) outranks an otherwise-equal card without one
    one = C((5, 1, 5, 7))
    none = C((5, 3, 3, 7))
    assert card_score(one, PLAIN) == card_score(none, PLAIN)   # equal without the rule
    assert card_score(one, fa) > card_score(none, fa)          # the 1 is worth something under it


def test_greedy_playout_returns_a_bounded_margin():
    a = tuple(_weak((5, 5, 5, 5)).id for _ in range(5))
    b = tuple(_weak((4, 4, 4, 4)).id for _ in range(5))
    v = greedy_playout(GameState(EMPTY_BOARD, (a, b), 0, PLAIN))
    assert -10 <= v <= 10


def _pool7():
    return [_weak(s).id for s in
            [(6, 6, 2, 2), (2, 2, 6, 6), (7, 3, 7, 3), (3, 7, 3, 7),
             (5, 5, 5, 5), (8, 2, 4, 6), (4, 8, 6, 4)]]


def test_recommend_screening_ranks_every_legal_deck():
    pool = _pool7()
    npc = [_weak((5, 5, 5, 5)).id for _ in range(5)]
    rec = recommend(npc, PLAIN, pool, shortlist_n=7, exact_k=0, top=4, swaps=False)
    assert rec.screened == comb(7, 5)
    assert 1 <= len(rec.results) <= 4
    worsts = [r.worst for r in rec.results]
    assert worsts == sorted(worsts, reverse=True)
    assert all(len(set(r.cards)) == 5 for r in rec.results)
    assert all(-10 <= r.first <= 10 and -10 <= r.second <= 10 for r in rec.results)


def test_recommend_scores_worst_case_over_multiple_npc_decks():
    pool = _pool7()
    strong = [_weak((7, 7, 7, 7)).id for _ in range(5)]     # a rough NPC deck
    weak = [_weak((1, 1, 1, 1)).id for _ in range(5)]       # a soft one
    vs_strong = recommend(strong, PLAIN, pool, shortlist_n=7, exact_k=0, top=4, swaps=False)
    vs_both = recommend([strong, weak], PLAIN, pool, shortlist_n=7, exact_k=0, top=4, swaps=False)
    assert vs_both.screened == comb(7, 5)
    # worst case over {strong, weak} can never beat the score against strong alone
    assert vs_both.best.worst <= vs_strong.best.worst + 1e-9
    worsts = [r.worst for r in vs_both.results]
    assert worsts == sorted(worsts, reverse=True)


@pytest.mark.slow
def test_order_rule_makes_recommend_optimise_the_hand_arrangement():
    from tt.recommend import _order_variants
    from tt.solver import solve

    ORDER = RuleSet(order=True)
    # lopsided sides: which edges are exposed - and captured - depends heavily on
    # the sequence the cards are forced out in.
    pool = [_weak(s).id for s in
            [(9, 1, 1, 9), (1, 9, 9, 1), (9, 9, 1, 1), (1, 1, 9, 9),
             (6, 4, 6, 4), (4, 6, 4, 6), (5, 5, 5, 5)]]
    npc = tuple(_weak((5, 5, 5, 5)).id for _ in range(5))

    rec = recommend(npc, ORDER, pool, shortlist_n=7, exact_k=4, top=3,
                    workers=1, swaps=False, order_probe=120)
    best = rec.best
    assert best.exact

    # the reported margins belong to exactly this left-to-right arrangement
    f = solve(GameState(EMPTY_BOARD, (best.cards, npc), 0, ORDER))
    s = solve(GameState(EMPTY_BOARD, (best.cards, npc), 1, ORDER))
    assert (f, s) == (best.first, best.second)

    # and it is the best arrangement of those five cards on worst case
    variants = _order_variants(best.cards)
    worsts = [min(solve(GameState(EMPTY_BOARD, (p, npc), 0, ORDER)),
                  solve(GameState(EMPTY_BOARD, (p, npc), 1, ORDER))) for p in variants]
    assert best.worst == max(worsts)
    assert min(worsts) < max(worsts)          # order genuinely mattered here


def test_order_probe_is_a_noop_when_order_is_off():
    from tt.recommend import _probe_orders, _screen_order

    deck = tuple(_weak((3, 5, 7, 2)).id for _ in range(1)) + \
        tuple(_weak(s).id for s in [(4, 4, 4, 4), (6, 2, 6, 2), (2, 6, 2, 6), (5, 5, 1, 9)])
    npc = [tuple(_weak((5, 5, 5, 5)).id for _ in range(5))]
    assert _probe_orders(deck, npc, PLAIN, keep=12) == [deck]
    assert _screen_order(deck, npc, PLAIN) == deck


@pytest.mark.slow
def test_recommend_exact_slice_and_swaps():
    pool = _pool7()
    npc = [_weak((5, 5, 5, 5)).id for _ in range(5)]
    rec = recommend(npc, PLAIN, pool, shortlist_n=7, exact_k=3, top=3, workers=1)
    assert rec.best.exact
    worsts = [r.worst for r in rec.results]
    assert worsts == sorted(worsts, reverse=True)
    for slot, out_n, in_n, delta in rec.swaps:
        assert 0 <= slot < 5 and delta > 0


@pytest.mark.slow
def test_recommend_parallel_matches_serial():
    # exact_k >= 6 puts the run over the pool threshold; forked workers inherit
    # the test cards, and the parallel result must match the serial one exactly.
    pool = _pool7()
    npc = [_weak((6, 4, 6, 4)).id for _ in range(5)]
    kw = dict(shortlist_n=7, exact_k=6, top=4, swaps=False, opp="greedy")
    serial = recommend(npc, PLAIN, pool, workers=1, **kw)
    parallel = recommend(npc, PLAIN, pool, workers=2, **kw)
    assert [r.cards for r in serial.results] == [r.cards for r in parallel.results]
    assert [r.worst for r in serial.results] == [r.worst for r in parallel.results]
