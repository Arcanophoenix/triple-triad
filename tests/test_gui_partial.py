"""The GUI's partial-state machinery for a variable-deck NPC whose drawn cards
aren't all known yet (hands[1] carries None for an unidentified card)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import gui  # noqa: E402
from tt.data import resolve  # noqa: E402


def _ids(*names):
    return [resolve(n).id for n in names]


def _fresh_partial(you_first=True):
    fixed = _ids("Behemoth Card", "Blue Dragon Card", "Bomb Card")
    pool = _ids("Scarface Bugaal Ja Card", "Chocobo Card", "Ahriman Card", "Coblyn Card")
    you = _ids("Spriggan Card", "Mandragora Card", "Dodo Card", "Coeurl Card", "Bomb Card")
    hand1 = fixed + [None, None]
    return gui._partial_state({"rules": ["Plus", "Three Open"]},
                              (None,) * 9, you, hand1, pool, 0 if you_first else 1, "greedy")


def test_partial_flags_and_completions():
    st = _fresh_partial()
    assert gui._is_partial(st)
    assert gui._holes(st["hands"][1]) == [3, 4]
    comps = list(gui._completions(st))
    assert len(comps) == 6                       # C(4 pool, 2 holes)
    for cs in comps:
        assert None not in cs.hands[1] and len(cs.hands[1]) == 5
        assert set(cs.hands[1][:3]) == set(st["hands"][1][:3])   # fixed cards kept


def _swap(you_names, entry, out_name, in_name):
    # _swap_hands only touches `self` in the fixed-deck branch, so None is fine here
    return gui.Handler._swap_hands(
        None, _ids(*you_names), entry, "Yellow Moon", {}, out_name, in_name)


_YM = {
    "fixed": ["Gaius van Baelsar Card", "Gaelicat Card"],
    "pool": ["Yugiri Mistwalker Card", "Gerolt Card", "Rhitahtyn sas Arvina Card",
             "Tidus Card", "Shiva Card"],
    "draw": 3,
}
_MY5 = ["Dodo Card", "Sabotender Card", "Bomb Card", "Mandragora Card", "Coeurl Card"]


def test_swap_receiving_a_pool_card():
    you5, hand1, pool, them5 = _swap(_MY5, _YM, "Bomb Card", "Tidus Card")
    assert them5 is None
    assert resolve("Tidus Card").id in you5 and resolve("Bomb Card").id not in you5
    # your Bomb is now an explicit NPC card; two holes left
    assert hand1[:3] == _ids("Gaius van Baelsar Card", "Gaelicat Card", "Bomb Card")
    assert hand1[3:] == [None, None]
    assert resolve("Tidus Card").id not in pool          # you hold it now
    assert len(pool) == 4


def test_swap_receiving_a_fixed_card():
    you5, hand1, pool, them5 = _swap(_MY5, _YM, "Coeurl Card", "Gaelicat Card")
    assert them5 is None
    assert hand1[0] == resolve("Gaius van Baelsar Card").id
    assert hand1[1] == resolve("Coeurl Card").id         # your card took Gaelicat's slot
    assert hand1[2:] == [None, None, None]
    assert len(pool) == 5                                # full pool still in play


def test_swap_rejects_a_card_you_do_not_hold():
    import pytest
    with pytest.raises(ValueError):
        _swap(_MY5, _YM, "Ifrit Card", "Tidus Card")


def test_swap_may_hand_you_a_second_copy_of_a_card_you_run():
    # FFXIV's Swap does not prevent duplicates: you run Shiva, the NPC's Shiva
    # comes to you, and you now hold two.  The solver collapses them.
    mine = ["Dodo Card", "Sabotender Card", "Bomb Card", "Mandragora Card", "Shiva Card"]
    you5, hand1, pool, them5 = _swap(mine, _YM, "Bomb Card", "Shiva Card")
    assert you5.count(resolve("Shiva Card").id) == 2
    from tt.model import EMPTY_BOARD, GameState, RuleSet
    from tt.solver import legal_moves
    st = GameState(EMPTY_BOARD, (tuple(you5), tuple(hand1[:3] + [pool[0], pool[1]])),
                   0, RuleSet.from_names(["Ascension"]))
    idxs = {i for i, _ in legal_moves(st)}
    assert len(idxs) == 4          # the doubled Shiva is offered once, not twice


def test_arr_portraits_are_matched_by_name_not_number():
    # arrtripletriad.com numbers cards differently from the wiki (it interleaves
    # the FF-crossover cards), so the portrait for Opo-opo (wiki #156) is NOT
    # 156.png.  The mapping must be by name.
    opo = resolve("Opo-opo Card")
    assert gui._ARR_BY_ID.get(opo.id) not in (None, "156.png")
    assert gui._ARR_BY_ID[resolve("Dodo Card").id] == "1.png"          # low ids still line up
    assert gui._ARR_BY_ID.get(resolve("Cloud Strife Card").id)         # FF cards get portraits now
    assert len(gui._ARR_BY_ID) > 400


def test_partial_state_scoring_and_terminal():
    st = _fresh_partial()
    assert st["terminal"] is False and st["scoreYou"] == 5 and st["npcPool"]
    # once both holes are filled it is no longer partial
    concrete = _fresh_partial()
    concrete["hands"][1] = concrete["hands"][1][:3] + _ids("Ahriman Card", "Chocobo Card")
    assert not gui._is_partial(concrete)
    assert list(gui._completions(concrete))  # still enumerable (one completion)


def test_refine_solves_fewer_decks_exactly_under_swap():
    """exact_k is near-free for most rules (the costly pass scales with `top`,
    not exact_k) but not under Swap, where it costs exact_k x 25 exchanges x 2
    sides of solves.  Measured on Kaizan: 8 -> +6.16 in 247s, 25 -> +6.24 in
    363s, i.e. 116s for 0.08 of margin.  Swap averages over the 25 exchanges
    anyway, which smooths the screen noise a wide slice exists to correct."""
    from tt.model import RuleSet
    assert gui.refine_exact_k(RuleSet()) == 25
    assert gui.refine_exact_k(RuleSet(plus=True, same=True)) == 25
    assert gui.refine_exact_k(RuleSet(swap=True)) == 8
    assert gui.refine_exact_k(RuleSet(swap=True, chaos=True)) == 8
