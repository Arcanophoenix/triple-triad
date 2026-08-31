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
