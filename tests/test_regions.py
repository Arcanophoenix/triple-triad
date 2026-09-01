import json

import pytest

from tt import regions as R
from tt.data import load_npcs


def test_known_zones_map_to_regions():
    assert R.region_for_zone("South Shroud") == "The Black Shroud"
    assert R.region_for_zone("Coerthas Central Highlands") == "Coerthas and Mor Dhona"
    assert R.region_for_zone("Kugane") == "Othard"
    assert R.region_for_zone("Tuliyollal") == "Tural"
    assert R.region_for_zone("The Gold Saucer") == R.FIXED
    assert R.region_for_zone("Nowhere At All") is None
    assert R.region_for_zone(None) is None


def test_every_current_npc_zone_is_mapped():
    """Guards against npcs.json gaining a zone the region map doesn't know."""
    unmapped = sorted({(n.get("location") or {}).get("zone")
                       for n in load_npcs() if R.region_for_npc(n) is None})
    assert not unmapped, f"add these zones to tt/regions.py: {unmapped}"


def test_combine_is_match_first_and_deduped():
    assert R.combine(["Order"], ["Same", "order"]) == ["Order", "Same"]
    assert R.combine(["Plus", "Same"], []) == ["Plus", "Same"]
    assert R.combine([], ["Same"]) == ["Same"]


def test_effective_rules_layers_regional_over_match(monkeypatch):
    monkeypatch.setattr(R, "load_regional",
                        lambda: {"regions": {"The Black Shroud": {"rules": ["Same"], "date": "x"}}})
    npc = {"rules": ["Descension", "Plus"], "location": {"zone": "Old Gridania"}}

    assert R.effective_rules(npc) == ["Descension", "Plus", "Same"]
    assert R.effective_rules(npc, use_regional=False) == ["Descension", "Plus"]
    assert R.effective_rules(npc, override="Reverse, Fallen Ace") == ["Reverse", "Fallen Ace"]
    assert R.effective_rules(npc, deck_entry={"rules": ["Order"]}) == ["Order", "Same"]


def test_fixed_and_unknown_regions_contribute_no_regional_rules(monkeypatch):
    monkeypatch.setattr(R, "load_regional",
                        lambda: {"regions": {"Whatever": {"rules": ["Plus"], "date": "x"}}})
    saucer = {"rules": ["Three Open", "Chaos"], "location": {"zone": "The Gold Saucer"}}
    mystery = {"rules": ["Plus"], "location": {"zone": "Void Zone"}}
    assert R.effective_rules(saucer) == ["Three Open", "Chaos"]
    assert R.effective_rules(mystery) == ["Plus"]


def test_set_and_clear_regional_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("tt.paths.FROZEN", False)
    monkeypatch.setattr("tt.paths.BUNDLED_DATA", tmp_path)

    assert R.regional_rules("Thanalan") == ([], None)
    R.set_regional("Thanalan", ["Same", "Plus"], on="2026-08-31")
    assert R.regional_rules("Thanalan") == (["Same", "Plus"], "2026-08-31")

    on_disk = json.loads((tmp_path / "regional.json").read_text())
    assert on_disk["regions"]["Thanalan"]["rules"] == ["Same", "Plus"]

    R.clear_regional("Thanalan")
    assert R.regional_rules("Thanalan") == ([], None)


def test_set_regional_rejects_bad_input(tmp_path, monkeypatch):
    monkeypatch.setattr("tt.paths.FROZEN", False)
    monkeypatch.setattr("tt.paths.BUNDLED_DATA", tmp_path)
    with pytest.raises(ValueError):
        R.set_regional("Atlantis", ["Same"])
    with pytest.raises(Exception):
        R.set_regional("Thanalan", ["Not A Rule"])


def test_is_stale():
    assert R.is_stale(None) is True
    assert R.is_stale("not-a-date") is True
    assert R.is_stale("2000-01-01") is True
