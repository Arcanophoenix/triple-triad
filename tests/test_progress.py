"""Story-progress gating: which NPCs the player can actually reach."""
import json

import pytest

from tt import progress as P
from tt.data import load_npcs
from tt.regions import region_for_npc


@pytest.fixture(autouse=True)
def _isolate_collection(tmp_path, monkeypatch):
    """save_progress writes collection.json under USER_DIR, which in a source
    checkout is the real data/ - never let the suite touch the player's file."""
    monkeypatch.setattr("tt.paths.USER_DIR", tmp_path)


def test_expansion_is_read_from_the_patch():
    assert P.expansion_of(P.npc_patch({"patch": "2.51"})) == "ARR"
    assert P.expansion_of(P.npc_patch({"patch": "3.4"})) == "HW"
    assert P.expansion_of(P.npc_patch({"patch": "7.45"})) == "DT"
    assert P.npc_patch({"patch": "nonsense"}) is None
    assert P.npc_patch({}) is None


def test_patch_strings_order_correctly_as_numbers():
    """Two-decimal patch strings compare correctly as floats; x.45 < x.5 is the
    case that would break a naive split-on-dot integer compare."""
    p = lambda s: P.npc_patch({"patch": s})
    assert p("4.45") < p("4.5") < p("4.55")
    assert p("7.5") < p("7.51")
    assert p("2.35") < p("2.51")


def test_expansion_names_mean_the_whole_expansion():
    """'ShB' has to include 5.45 content, or finishing Shadowbringers would still
    hide most Shadowbringers NPCs."""
    assert P.parse_progress("ShB") == pytest.approx(5.99)
    assert P.parse_progress("shadowbringers") == pytest.approx(5.99)
    assert P.parse_progress("6.3") == pytest.approx(6.3)
    assert P.parse_progress(None) is None
    with pytest.raises(ValueError):
        P.parse_progress("Endwalkerish")


def test_reachability():
    shb = P.parse_progress("ShB")
    assert P.is_reachable({"patch": "2.0"}, shb) is True
    assert P.is_reachable({"patch": "5.45"}, shb) is True
    assert P.is_reachable({"patch": "6.0"}, shb) is False
    # unset progress filters nothing; an NPC with no patch is never hidden
    assert P.is_reachable({"patch": "7.0"}, None) is True
    assert P.is_reachable({"patch": None}, shb) is True


def test_progress_round_trips_without_disturbing_the_collection(tmp_path):
    col = tmp_path / "collection.json"
    col.write_text(json.dumps({"owned": ["Dodo Card"], "decks": {"a": []}}))
    P.save_progress("HW")
    assert P.load_progress() == pytest.approx(3.99)
    on_disk = json.loads(col.read_text())
    assert on_disk["owned"] == ["Dodo Card"] and on_disk["decks"] == {"a": []}
    P.save_progress(None)                       # clearing leaves the rest alone
    assert P.load_progress() is None
    assert "progress" not in json.loads(col.read_text())


def test_every_npc_has_a_usable_patch():
    """The gate is only as good as the data; a missing patch silently un-gates."""
    bad = [n["name"] for n in load_npcs() if P.npc_patch(n) is None]
    assert not bad, f"NPCs with no parseable patch: {bad}"


def test_patch_is_never_earlier_than_the_zone_would_imply():
    """Why the patch alone is a sound gate: an NPC cannot stand in a zone that did
    not exist when they were added, so the patch is always at least as late as the
    zone's expansion.  If this ever fails, zone-based gating would be catching
    something the patch misses and this module's central assumption is wrong.
    """
    region_exp = {"La Noscea": 2, "The Black Shroud": 2, "Thanalan": 2,
                  "Coerthas and Mor Dhona": 2, "Abalathia": 3, "Dravania": 3,
                  "Gyr Abania": 4, "Othard": 4, "Norvrandt": 5, "Ilsabard": 6,
                  "Tural": 7}
    offenders = []
    for n in load_npcs():
        major_zone = region_exp.get(region_for_npc(n))
        patch = P.npc_patch(n)
        if major_zone is not None and patch is not None and int(patch) < major_zone:
            offenders.append((n["name"], n["location"]["zone"], patch))
    assert not offenders, f"zone later than patch: {offenders}"


# --- difficulty's accurate re-check band -------------------------------------

def _row(edge):
    return (0.0, "easy", {"name": f"npc{edge}"}, edge)


def test_borderline_keeps_rows_the_cheap_screen_could_be_understating():
    """The cheap screen understated by up to 6 in every measured case, so a row
    at -6 can really be 0 and must survive to the accurate pass; filtering on the
    cheap number alone is what hid winnable matchups."""
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
    import difficulty as D

    rows = [_row(+8), _row(0), _row(-6), _row(-6.5), _row(None)]
    kept = [r[3] for r in D.borderline(rows, cap=0)]
    assert kept == [8, 0, -6]          # -6.5 is out of reach, None has no deck
    # best-looking first, so a cap keeps the ones that can actually make the list
    assert [r[3] for r in D.borderline([_row(-4), _row(+2), _row(-1)], cap=2)] == [2, -1]
