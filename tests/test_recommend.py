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


# --- Swap rule --------------------------------------------------------------

def test_matchups_is_identity_without_swap():
    from tt.recommend import _matchups
    deck, npc = (1, 2, 3, 4, 5), (6, 7, 8, 9, 10)
    assert _matchups(deck, npc, PLAIN) == [(deck, npc)]


def test_swap_matchups_cover_every_pairing_exactly_once():
    from tt.recommend import _matchups
    deck, npc = (1, 2, 3, 4, 5), (6, 7, 8, 9, 10)
    ms = _matchups(deck, npc, RuleSet(swap=True))
    assert len(ms) == 25
    assert len(set(ms)) == 25
    for mine, theirs in ms:
        # exactly one card crossed each way, and both hands stay five cards
        assert len(mine) == len(theirs) == 5
        gained = set(mine) - set(deck)
        lost = set(deck) - set(mine)
        assert len(gained) == len(lost) == 1
        # the card you gained is the one they lost, and vice versa
        assert gained == set(npc) - set(theirs)
        assert lost == set(theirs) - set(npc)


def test_swap_keeps_the_swapped_card_in_the_slot_it_replaced():
    # matters under Order, where the hand plays strictly left-to-right
    from tt.recommend import _matchups
    deck, npc = (1, 2, 3, 4, 5), (6, 7, 8, 9, 10)
    for mine, _ in _matchups(deck, npc, RuleSet(swap=True)):
        moved = [i for i, c in enumerate(mine) if c != deck[i]]
        assert len(moved) == 1
        assert mine[:moved[0]] == deck[:moved[0]]
        assert mine[moved[0] + 1:] == deck[moved[0] + 1:]


def test_swap_sample_is_stratified_over_your_slots():
    """A truncated probe must cover every card of yours before repeating one -
    losing your best card is the dominant risk, so a sample that missed a slot
    would systematically misjudge decks built around that slot."""
    from tt.recommend import _matchups
    deck, npc = (1, 2, 3, 4, 5), (6, 7, 8, 9, 10)
    first5 = _matchups(deck, npc, RuleSet(swap=True), limit=5)
    assert len(first5) == 5
    given_up = [next(c for c in deck if c not in mine) for mine, _ in first5]
    assert sorted(given_up) == list(deck)


def test_swap_margin_is_the_average_over_outcomes_not_the_worst():
    from tt.recommend import _avg_sides
    deck, npc = (1, 2, 3, 4, 5), (6, 7, 8, 9, 10)
    rules = RuleSet(swap=True)
    seen = []
    def ev(st):
        seen.append(st.hands)
        return len(seen)                      # distinct, increasing values
    first, second = _avg_sides(deck, npc, rules, ev)
    assert len(seen) == 50                    # 25 outcomes x 2 coin-toss sides
    # the mean of the values handed back, not their min
    assert first == sum(range(1, 50, 2)) / 25
    assert second == sum(range(2, 51, 2)) / 25


def test_swap_handles_a_card_both_decks_hold():
    """Decks can share a card (you and the NPC both field Papalymo & Yda).  Trading
    it for itself is a legitimate no-op, and every outcome must still be a 5-card
    hand - this is the case a naive 'exactly one slot changed' assumption breaks."""
    from tt.recommend import _matchups
    deck, npc = (1, 2, 3, 4, 5), (6, 7, 3, 8, 9)      # card 3 in both
    ms = _matchups(deck, npc, RuleSet(swap=True))
    assert len(ms) == 25
    noops = [(m, t) for m, t in ms if m == deck]
    assert len(noops) == 1 and noops[0][1] == npc     # only 3-for-3, and it's clean
    for mine, theirs in ms:
        assert len(mine) == len(theirs) == 5
        assert sorted(mine + theirs) == sorted(deck + npc)   # no card conjured or lost


# --- Chaos: no position is solvable, so nothing may claim to be solved --------

def _chaos_board(cards, empty=4):
    """A Chaos position with ``empty`` free cells, reached by a fixed opening so the
    test is deterministic."""
    from tt.solver import apply
    ids = [c.id for c in cards]
    st = GameState(EMPTY_BOARD, (tuple(ids[:5]), tuple(ids[5:])), 0,
                   RuleSet(chaos=True))
    for cell in (4, 0, 8, 2, 6)[:9 - empty]:
        st = apply(st, 0, cell)
    return st


def _reference_chaos_value(st):
    """Independent, memo-free expectimax straight off the rule: the mover picks the
    cell, the card is a uniform draw from their hand."""
    from collections import Counter
    from tt.model import is_terminal, value_a
    from tt.solver import apply
    if is_terminal(st):
        return value_a(st)
    hand = st.hands[st.to_move]
    cells = [i for i in range(9) if st.board[i] is None]
    pick = max if st.to_move == 0 else min
    exp = 0.0
    for cid, k in Counter(hand).items():
        hi = hand.index(cid)
        exp += (k / len(hand)) * pick(_reference_chaos_value(apply(st, hi, c)) for c in cells)
    return exp


def test_chaos_solve_matches_an_independent_expectimax():
    """Pins tt.solver._chaos_value, including its transposition-table memoisation:
    Chaos values are window-independent expectations, so caching them must be
    exactly value-neutral."""
    from tt.solver import solve
    cards = [C((3, 5, 2, 6)), C((7, 2, 4, 3)), C((2, 6, 6, 2)), C((5, 3, 3, 5)),
             C((4, 4, 7, 1)), C((6, 2, 5, 4)), C((1, 7, 3, 5)), C((5, 5, 2, 6)),
             C((3, 4, 6, 3)), C((6, 6, 1, 4))]
    st = _chaos_board(cards, empty=4)
    assert solve(st, "optimal") == pytest.approx(_reference_chaos_value(st))


def test_chaos_exact_pass_is_a_deep_screen_not_a_greedy_playout():
    """analyze() cannot rank cards you do not choose, so the exact pass used to fall
    through to a single greedy playout - shallower than the screen it was meant to
    refine, and optimistic by ~1.9 margin points."""
    from tt.recommend import CHAOS_TAIL, _exact_value, screen_value
    cards = [C((3, 5, 2, 6)), C((7, 2, 4, 3)), C((2, 6, 6, 2)), C((5, 3, 3, 5)),
             C((4, 4, 7, 1)), C((6, 2, 5, 4)), C((1, 7, 3, 5)), C((5, 5, 2, 6)),
             C((3, 4, 6, 3)), C((6, 6, 1, 4))]
    st = _chaos_board(cards, empty=6)
    chaos = RuleSet(chaos=True)
    assert _exact_value(st, chaos, "optimal") == screen_value(st, CHAOS_TAIL, "optimal")


def _positions(rules, empty):
    """One position per coin-toss side, ``empty`` cells free, played out along a
    fixed line so the test is deterministic."""
    from tt.solver import apply
    cards = [C((3, 5, 2, 6)), C((7, 2, 4, 3)), C((2, 6, 6, 2)), C((5, 3, 3, 5)),
             C((4, 4, 7, 1)), C((6, 2, 5, 4)), C((1, 7, 3, 5)), C((5, 5, 2, 6)),
             C((3, 4, 6, 3)), C((6, 6, 1, 4))]
    ids = [c.id for c in cards]
    out = []
    for side in (0, 1):
        st = GameState(EMPTY_BOARD, (tuple(ids[:5]), tuple(ids[5:])), side, rules)
        for cell in (4, 0, 8, 2, 6)[:9 - empty]:
            st = apply(st, 0, cell)
        out.append(st)
    return out


NON_CHAOS = (PLAIN, RuleSet(plus=True), RuleSet(same=True), RuleSet(order=True))


def test_exact_value_solves_fully_when_chaos_is_off():
    """Without Chaos the exact pass is a real full-board solve - and it calls solve()
    rather than analyze().best.value because the two agree (analyze's ranking maximum
    IS the game value) while solve gets alpha-beta at the root."""
    from tt.solver import analyze, solve
    from tt.recommend import _exact_value
    for rules in NON_CHAOS:
        for st in _positions(rules, empty=6):
            for opp in ("optimal", "greedy"):
                v = _exact_value(st, rules, opp)
                assert v == solve(st, opp) == analyze(st, opp=opp).best.value


@pytest.mark.slow
def test_exact_value_matches_analyze_from_an_empty_board():
    """The same equivalence on the position the recommender actually evaluates - a
    full opening, where analyze searches all 45 root moves on a full window."""
    from tt.solver import analyze, solve
    from tt.recommend import _exact_value
    for rules in NON_CHAOS:
        for st in _positions(rules, empty=9):
            for opp in ("optimal", "greedy"):
                v = _exact_value(st, rules, opp)
                assert v == solve(st, opp) == analyze(st, opp=opp).best.value


def test_chaos_recommendations_are_never_labelled_exact():
    """21 NPCs play Chaos.  Their margins are estimates, and the CLI's `(est)` tag
    keys off DeckResult.exact - so it must not read True there."""
    cards = [C((3, 5, 2, 6)), C((7, 2, 4, 3)), C((2, 6, 6, 2)), C((5, 3, 3, 5)),
             C((4, 4, 7, 1)), C((6, 2, 5, 4)), C((1, 7, 3, 5))]
    pool = [c.id for c in cards]
    npc = tuple(pool[:5])
    rec = recommend(list(npc), RuleSet(chaos=True), pool, shortlist_n=6,
                    exact_k=2, top=2, screen_tail=4, swaps=False, workers=1)
    assert rec.results
    assert all(r.exact is False for r in rec.results)


def test_non_chaos_recommendations_are_still_labelled_exact():
    cards = [C((3, 5, 2, 6)), C((7, 2, 4, 3)), C((2, 6, 6, 2)), C((5, 3, 3, 5)),
             C((4, 4, 7, 1)), C((6, 2, 5, 4)), C((1, 7, 3, 5))]
    pool = [c.id for c in cards]
    rec = recommend(list(pool[:5]), PLAIN, pool, shortlist_n=6, exact_k=2, top=2,
                    screen_tail=4, swaps=False, workers=1)
    assert rec.results and all(r.exact is True for r in rec.results)


def test_recommend_does_not_leak_worker_processes():
    """recommend() shut its pool down with `wait=False`, which returns before the
    executor's manager thread and forked workers are gone.  They then outlive the
    call - burning CPU next to a running game, and leaving the interpreter's
    atexit hook to join them, which intermittently hung the process outright
    (observed: a benchmark printed its complete results and sat there for 27
    minutes; a 10-call loop hung 1 run in 6).

    The hang is a race and so untestable directly - a subprocess test for it
    passed happily against the broken code.  The leak underneath it is not:
    `wait=False` leaves exactly the pool's workers alive here, `wait=True` leaves
    none.  Assert on that.

    Worth guarding because the GUI server is long-lived and calls recommend() on
    every Recommend / refine click.
    """
    import multiprocessing
    pool = _pool7()
    npc = [_weak((5, 5, 5, 5)).id for _ in range(5)]
    # exact_k >= 6 is what puts the run over the threshold for a real pool
    recommend(npc, PLAIN, pool, shortlist_n=7, exact_k=6, top=3, swaps=False,
              opp="greedy", workers=2)
    assert multiprocessing.active_children() == []
