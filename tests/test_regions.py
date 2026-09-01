import json
from collections import Counter

import pytest

from tt import regions as R
from tt.data import load_npcs


@pytest.fixture(autouse=True)
def _isolate_observation_log(tmp_path, monkeypatch):
    """set_regional() appends to the observation log under USER_DIR, which in a
    source checkout is the real data/.  Redirect it for every test in this file
    so the suite can never write into the user's own history."""
    monkeypatch.setattr("tt.paths.USER_DIR", tmp_path)


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


# --- rule-days and the observation log ---------------------------------------

def _dt(iso):
    from datetime import datetime
    return datetime.fromisoformat(iso)


def test_rule_day_boundary_is_1500_utc():
    """Regionals roll at 15:00 UTC, so a rule-day is named after the date it
    starts on - 14:59 still belongs to the previous one."""
    assert R.rule_day(_dt("2026-09-01T14:59:59+00:00")).isoformat() == "2026-08-31"
    assert R.rule_day(_dt("2026-09-01T15:00:00+00:00")).isoformat() == "2026-09-01"
    assert R.rule_day(_dt("2026-09-01T23:30:00+00:00")).isoformat() == "2026-09-01"
    # a non-UTC reading is converted, not assumed
    assert R.rule_day(_dt("2026-09-02T00:30:00+02:00")).isoformat() == "2026-09-01"


def test_log_observation_skips_an_unchanged_repeat():
    assert R.log_observation("Thanalan", ["Same"], "2026-09-01") is True
    assert R.log_observation("Thanalan", ["Same"], "2026-09-01") is False
    assert len(R.load_history()) == 1


def test_a_corrected_reading_is_appended_and_wins():
    R.log_observation("Thanalan", ["Same"], "2026-09-01")
    R.log_observation("Thanalan", ["Plus", "Reverse"], "2026-09-01")
    assert len(R.load_history()) == 2                    # the correction is kept
    obs = R.observations()
    assert obs[("2026-09-01", "Thanalan")] == ["Plus", "Reverse"]   # ...and wins


def test_set_regional_records_an_observation(tmp_path, monkeypatch):
    monkeypatch.setattr("tt.paths.FROZEN", False)
    monkeypatch.setattr("tt.paths.BUNDLED_DATA", tmp_path)
    R.set_regional("Thanalan", ["Same"], on="2026-09-01")
    assert R.observations() == {("2026-09-01", "Thanalan"): ["Same"]}


def test_consecutive_pairs_do_not_bridge_a_gap():
    """You cannot compare across a day you never looked at."""
    for day, rules in (("2026-09-01", ["Same"]), ("2026-09-02", ["Same"]),
                       ("2026-09-05", ["Plus"])):
        R.log_observation("Thanalan", rules, day)
    pairs = R.consecutive_pairs(R.observations())
    assert pairs == {"Thanalan": [(["Same"], ["Same"])]}   # 02->05 is not a pair
    assert R.repeat_rate(R.observations()) == (1, 1)


def test_repeat_rate_ignores_rule_order():
    R.log_observation("Thanalan", ["Same", "Plus"], "2026-09-01")
    R.log_observation("Thanalan", ["Plus", "Same"], "2026-09-02")
    assert R.repeat_rate(R.observations()) == (1, 1)


def test_cross_region_agreement_only_compares_within_a_day():
    R.log_observation("Thanalan", ["Same"], "2026-09-01")
    R.log_observation("La Noscea", ["Same"], "2026-09-01")
    R.log_observation("Othard", ["Plus"], "2026-09-01")
    R.log_observation("Tural", ["Same"], "2026-09-02")     # different day, no pairs
    same, total = R.cross_region_agreement(R.observations())
    assert (same, total) == (1, 3)                          # 3 pairs, only one match


def test_seed_history_folds_in_current_regional_json(tmp_path, monkeypatch):
    monkeypatch.setattr("tt.paths.FROZEN", False)
    monkeypatch.setattr("tt.paths.BUNDLED_DATA", tmp_path)
    (tmp_path / "regional.json").write_text(json.dumps({"regions": {
        "Thanalan": {"rules": ["Same"], "date": "2026-08-30"},
        "Othard": {"rules": ["Plus"], "date": "2026-08-30"}}}))
    assert R.seed_history() == 2
    assert R.seed_history() == 0                            # idempotent
    assert len(R.load_history()) == 2


def test_no_regional_rules_is_a_real_observation(tmp_path, monkeypatch):
    """"None / None" on the Match Registration screen is a reading, not a gap.
    It has to round-trip as an empty list and stay distinguishable from a region
    that was never looked at - otherwise a logged day counts as a missing one and
    every frequency below is computed over the wrong denominator."""
    monkeypatch.setattr("tt.paths.FROZEN", False)
    monkeypatch.setattr("tt.paths.BUNDLED_DATA", tmp_path)
    R.set_regional("The Black Shroud", [], on="2026-09-01")

    saved = R.load_regional()["regions"]
    assert saved["The Black Shroud"]["rules"] == []      # recorded...
    assert "Thanalan" not in saved                       # ...vs never recorded
    assert R.observations() == {("2026-09-01", "The Black Shroud"): []}
    # and it contributes a day to the sample without contributing a rule
    assert R.rule_frequency(R.observations())["The Black Shroud"] == Counter()
