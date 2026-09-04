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


def test_card_ids_are_collects_own_id_not_the_in_game_number():
    """The export's `cards` are ffxivcollect.com/triad/cards/<id> ids, stored as
    Card.collect_id.  They match the in-game No. (= Card.number) for the low cards
    then diverge, because Collect interleaves the 15 FF-collab cards.

    The real regression: Gaelicat is No. 68 but collect_id 81, and No. 81 is
    Byblos.  An export listing 81 (its owner has Gaelicat) imported Byblos when
    the lookup went through the number.
    """
    names, unknown = C.map_cards([1])
    assert names == ["Dodo Card"] and unknown == []

    gaelicat = next(c for c in CARDS if c.name == "Gaelicat Card")
    assert (gaelicat.number, gaelicat.collect_id) == (68, 81)
    byblos = next(c for c in CARDS if c.name == "Byblos Card")
    assert byblos.number == 81
    assert C.map_cards([81])[0] == ["Gaelicat Card"]        # not Byblos


def test_ff_collab_cards_import_through_their_collect_id():
    """FF cards have no in-game No. but they DO have a collect_id, so a player who
    owns one gets it - the old number-based lookup silently dropped them."""
    ff = [c for c in CARDS if c.series == "ff" and c.collect_id]
    assert ff, "expected FF-collab cards with a collect_id"
    names, unknown = C.map_cards([ff[0].collect_id])
    assert names == [ff[0].name] and unknown == []


def test_unknown_ids_are_reported_not_dropped():
    names, unknown = C.map_cards([1, 999999])
    assert names == ["Dodo Card"] and unknown == [999999]
    names, unknown = C.map_npcs([424242])
    assert names == [] and unknown == [424242]


def test_every_main_series_card_has_a_collect_id():
    """The gate is only as good as the data; a card with collect_id 0 silently
    cannot be imported."""
    missing = [c.name for c in CARDS if c.series == "main" and not c.collect_id]
    assert not missing, f"main-series cards without a collect_id: {missing}"


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


def test_native_ids_are_literally_the_same_as_collects_id():
    """Collect doesn't invent its own numbering for either list - collect_id
    already IS the game's native Excel sheet row id, for both cards and NPCs
    (confirmed by comparing all 475 TripleTriadCard rows by name, zero
    mismatches, and Memeroon's real TripleTriad row 2293762). So a native
    client export needs no separate id mapping - map_cards/map_npcs already
    do the right thing."""
    gaelicat = next(c for c in CARDS if c.name == "Gaelicat Card")
    names, unknown = C.map_cards([gaelicat.collect_id])
    assert names == ["Gaelicat Card"] and unknown == []

    npc = next(n for n in load_npcs() if n.get("collect_id"))
    npc_names, unknown_n = C.map_npcs([npc["collect_id"]])
    assert npc_names == [npc["name"]] and unknown_n == []


def test_apply_native_export_merges_like_apply_export(tmp_path):
    (tmp_path / "collection.json").write_text(json.dumps(
        {"owned": ["Spriggan Card"], "npcs_beaten": ["Maisenta"]}))
    npc = next(n for n in load_npcs() if n.get("collect_id") and n["name"] != "Maisenta")

    r = C.apply_native_export({"owned_card_ids": [1], "beaten_npc_ids": [npc["collect_id"]]})

    assert r["cards_added"] == ["Dodo Card"]
    col = read_collection()
    assert set(col["owned"]) == {"Spriggan Card", "Dodo Card"}
    assert set(col["npcs_beaten"]) == {"Maisenta", npc["name"]}


def test_load_native_export_rejects_a_file_that_is_not_one(tmp_path):
    bad = tmp_path / "nope.json"
    bad.write_text('{"hello": 1}')
    with pytest.raises(ValueError, match="native client export"):
        C.load_native_export(bad)
