"""Importing an FFXIV Collect export, and the beaten-NPC list it fills in."""
import json

import pytest

from tt import collect as C
from tt.data import CARDS, load_npcs, read_collection


@pytest.fixture(autouse=True)
def _isolate_collection(tmp_path, monkeypatch):
    """The importer writes collection.json under USER_DIR, which in a source
    checkout is the real data/ - the suite must never touch the player's file."""
    monkeypatch.setattr("tt.paths.USER_DIR", tmp_path)


def test_card_ids_are_collect_numbers_not_our_ids():
    """Collect's "No." is Card.number for the 460 main-series cards, which is NOT
    our Card.id - number 1 is Dodo (id 0), and id 1 is a different card."""
    names, unknown = C.map_cards([1])
    assert names == ["Dodo Card"] and unknown == []
    assert CARDS[1].name != "Dodo Card"


def test_ff_collab_cards_cannot_arrive_and_are_reported():
    """Collect numbers only the main series; the 15 FF cards have no number, so
    their numbers collide with main-series ones and must never be guessed at."""
    ff = [c for c in CARDS if c.series == "ff"]
    assert ff, "expected FF-collab cards in the dataset"
    names, _ = C.map_cards([ff[0].number])
    assert all(CARDS[0].series == "main" for _ in names)
    assert all(n not in {c.name for c in ff} for n in names)


def test_unknown_ids_are_reported_not_dropped():
    names, unknown = C.map_cards([1, 999999])
    assert names == ["Dodo Card"] and unknown == [999999]
    names, unknown = C.map_npcs([424242])
    assert names == [] and unknown == [424242]


def test_npc_ids_map_to_the_roster():
    npcs = [n for n in load_npcs() if n.get("collect_id")]
    assert len(npcs) == len(load_npcs()) - 1      # everyone but Lewena
    names, unknown = C.map_npcs([npcs[0]["collect_id"], npcs[5]["collect_id"]])
    assert names == [npcs[0]["name"], npcs[5]["name"]] and unknown == []


def test_lewena_is_the_known_unimportable_npc():
    """FFXIV Collect has no entry for her, so no export can ever tick her.  If
    this starts failing, Collect added her and the note can go."""
    assert C.unimportable_npcs() == ["Lewena"]


def test_import_merges_rather_than_replacing(tmp_path):
    (tmp_path / "collection.json").write_text(json.dumps(
        {"owned": ["Spriggan Card"], "npcs_beaten": ["Maisenta"], "decks": {"x": []}}))
    npc = next(n for n in load_npcs() if n.get("collect_id"))
    r = C.apply_export({"cards": [1], "npcs": [npc["collect_id"]]})

    assert r["cards_added"] == ["Dodo Card"]
    assert r["cards_removed"] == [] and r["npcs_removed"] == []
    col = read_collection()
    assert set(col["owned"]) == {"Spriggan Card", "Dodo Card"}   # kept what was there
    assert set(col["npcs_beaten"]) == {"Maisenta", npc["name"]}
    assert col["decks"] == {"x": []}                             # untouched


def test_replace_makes_the_export_authoritative(tmp_path):
    (tmp_path / "collection.json").write_text(json.dumps(
        {"owned": ["Spriggan Card"], "npcs_beaten": ["Maisenta"]}))
    r = C.apply_export({"cards": [1], "npcs": []}, replace=True)
    assert r["cards_removed"] == ["Spriggan Card"]
    assert r["npcs_removed"] == ["Maisenta"]
    assert read_collection()["owned"] == ["Dodo Card"]


def test_set_beaten_round_trips_and_validates():
    name = load_npcs()[0]["name"]
    C.set_beaten(name, True)
    assert C.load_beaten() == {name}
    C.set_beaten(name, False)
    assert C.load_beaten() == set()
    with pytest.raises(ValueError):
        C.set_beaten("Nobody At All", True)


def test_load_export_rejects_a_file_that_is_not_an_export(tmp_path):
    bad = tmp_path / "nope.json"
    bad.write_text('{"hello": 1}')
    with pytest.raises(ValueError, match="FFXIV Collect export"):
        C.load_export(bad)
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    with pytest.raises(ValueError, match="valid JSON"):
        C.load_export(broken)
    with pytest.raises(ValueError, match="cannot read"):
        C.load_export(tmp_path / "missing.json")
