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


# --- NPCs tab: progress + import + suggest endpoints ------------------------

import json  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr("tt.paths.USER_DIR", tmp_path)
    (tmp_path / "collection.json").write_text(json.dumps(
        {"owned": ["Dodo Card", "Spriggan Card"], "decks": {}, "npcs_beaten": []}))
    return tmp_path


def test_progress_payload_round_trips(_isolated):
    from tt.progress import save_progress
    assert gui._progress_payload()["value"] is None
    save_progress("ShB")
    p = gui._progress_payload()
    assert p["expansion"] == "ShB" and "ShB" in p["label"]


def test_bootstrap_carries_expansion_per_npc_and_progress_block(_isolated):
    # exercise the same shape /api/bootstrap builds
    from tt.data import load_npcs
    from tt.progress import expansion_of, npc_patch
    exps = {expansion_of(npc_patch(n)) for n in load_npcs()}
    assert exps == {"ARR", "HW", "SB", "ShB", "EW", "DT"}   # every NPC lands somewhere


def test_import_endpoint_merges_and_reports(_isolated):
    from tt.collect import apply_export
    r = apply_export({"cards": [1], "npcs": []})   # No.1 == Dodo, already owned
    assert r["cards_added"] == [] and r["unknown_card_ids"] == []
    r = apply_export({"cards": [2], "npcs": []})   # No.2 == Tonberry, new
    assert r["cards_added"] == ["Tonberry Card"]


def test_suggest_skips_beaten_and_unreachable(_isolated, monkeypatch):
    from tt.collect import save_beaten
    from tt.progress import save_progress
    save_progress("ARR")                 # hide HW+ NPCs
    save_beaten(["Maisenta", "Roger"])   # and these two specifically

    # stand in for the HTTP handler's candidate-building block
    from tt.data import load_decks, load_npcs
    from tt.progress import is_reachable, load_progress
    beaten, decks, prog = {"Maisenta", "Roger"}, load_decks(), load_progress()
    cands = [n["name"] for n in load_npcs()
             if n["name"] not in beaten and n["name"] in decks
             and is_reachable(n, prog)]
    assert "Maisenta" not in cands and "Roger" not in cands
    assert "Aiglephine" not in cands           # patch 6.0, beyond ARR
    assert "Triple Triad Master" in cands      # ARR, unbeaten, has a deck


# --- Regional tab: overview payload + the None/None-vs-clear fix -----------

class _Cap(gui.Handler):
    """A Handler that captures _send instead of writing to a socket."""
    def __init__(self):                 # skip BaseHTTPRequestHandler's socket setup
        self.command = "POST"
        self.sent = None

    def _send(self, code, body, ctype="application/json"):
        self.sent = (code, body)


@pytest.fixture
def _regional_isolated(_isolated, monkeypatch):
    # set_regional/load_regional touch BUNDLED_DATA/regional.json when not frozen;
    # _isolated already points USER_DIR (the observation log) at tmp_path.
    monkeypatch.setattr("tt.paths.BUNDLED_DATA", _isolated)
    return _isolated


def test_regional_overview_shape_and_pattern(_regional_isolated):
    from tt.regions import set_regional
    set_regional("Thanalan", ["Same"], on="2026-09-01")
    set_regional("La Noscea", ["Plus", "Roulette"], on="2026-09-01")

    ov = gui._regional_overview()
    assert ov["regions"][0] == "La Noscea"
    assert ov["vocab"] and "Roulette" in ov["vocab"]
    assert ov["current"]["Thanalan"]["rules"] == ["Same"]
    assert ov["pattern"]["observations"] == 2
    assert ov["pattern"]["frequency"]["La Noscea"]["counts"]        # Counter.most_common list
    assert ov["pattern"]["crossRegion"]["total"] == 1              # two regions, one day
    assert ov["pattern"]["crossRegion"]["same"] == 0               # different rules
    # nothing was logged under *today's* rule-day, so every region is still to check
    assert set(ov["today"]["missing"]) == set(ov["regions"])
    assert ov["history"][-1]["region"] == "La Noscea"


def test_set_regional_endpoint_logs_none_none_as_a_real_reading(_regional_isolated):
    """The GUI used to send an empty ruleset to clear_regional, so a None/None
    screen could never be recorded.  It must now be logged like `--none`."""
    from tt.regions import load_history, load_regional

    h = _Cap()
    h._set_regional({"region": "The Black Shroud", "rules": []})   # screen showed None/None
    assert h.sent[0] == 200
    assert load_regional()["regions"]["The Black Shroud"]["rules"] == []   # an entry, not absent
    logged = [r for r in load_history() if r["region"] == "The Black Shroud"]
    assert logged and logged[-1]["rules"] == []
    assert "The Black Shroud" in h.sent[1]["today"]["logged"]      # counts as checked today


def test_set_regional_endpoint_clear_forgets_the_region(_regional_isolated):
    from tt.regions import load_regional
    gui.set_regional("Gyr Abania", ["Reverse"])
    assert "Gyr Abania" in load_regional()["regions"]

    h = _Cap()
    h._set_regional({"region": "Gyr Abania", "clear": True})
    assert "Gyr Abania" not in load_regional()["regions"]         # pointer dropped
    assert h.sent[1]["current"]["Gyr Abania"]["rules"] == []


# --- suggest: bias-aware buckets + budgeted accurate re-check --------------

def test_suggest_bucket_shifts_thresholds_for_the_screen_bias():
    b = gui._suggest_bucket
    # a screen value never overstates and runs ~4 low, so the bar is lower;
    # "close" is never reported off a screen read
    assert b(0.0, "screen") == "win"
    assert b(-0.5, "screen") == "likely"
    assert b(-5.9, "screen") == "likely"
    assert b(-6.5, "screen") == "notyet"
    # an accurate value is taken at face value
    assert b(0.0, "accurate") == "close"
    assert b(3.0, "accurate") == "likely"
    assert b(6.0, "accurate") == "win"
    assert b(-3.0, "accurate") == "notyet"
    assert b(None, "screen") == "unknown"


def test_recheck_cost_orders_fast_rulesets_first():
    cost = gui.Handler._recheck_cost
    assert cost({}, {"rules": ["Three Open"]}) == 0
    assert cost({}, {"rules": ["Chaos", "Roulette"]}) == 2
    assert cost({"rules": ["Swap"]}, {}) == 1          # falls back to the npc's rules


def test_npc_portrait_map_points_at_real_saved_images():
    # reference/NPCs/ is gitignored (a re-downloadable wiki mirror), so a bare
    # checkout has none of it; scripts/fetch_npc_portraits.py populates it.
    m = gui._NPC_PORTRAIT
    if not m:
        pytest.skip("reference/NPCs/ not populated here")
    from tt.data import load_npcs
    roster = {n["name"] for n in load_npcs()}
    npc_dir = gui.NPCS_DIR.resolve()
    for name, path in m.items():
        assert name in roster                       # keyed by the real roster name
        assert path.is_file() and npc_dir in path.resolve().parents
        assert path.suffix.lower() in (".png", ".jpg", ".jpeg")
    assert "Baderon" in m           # one of the originally-saved pages
    assert "Arsieu" not in m        # a generic NPC with no wiki portrait


def test_chaos_and_swap_are_skipped_by_the_live_recheck():
    slow = gui.Handler._too_slow_to_recheck
    assert slow({}, {"rules": ["Chaos"]})
    assert slow({}, {"rules": ["Swap", "Same"]})
    assert not slow({}, {"rules": ["Roulette", "Plus"]})   # slow-ish but still tractable
    assert not slow({"rules": ["Order"]}, {})


def test_suggest_rechecks_the_borderline_band_and_sorts_by_bucket(_isolated, monkeypatch):
    monkeypatch.setattr(gui, "_owned_ids", lambda: [1, 2, 3, 4, 5])

    from tt.data import load_decks, load_npcs
    decks = load_decks()
    order = sorted((n for n in load_npcs() if n["name"] in decks),
                   key=lambda n: (n.get("mgp_win") or 0, n["name"]))
    # three candidates the live re-check will actually attempt (no Chaos/Swap)
    tractable = [n["name"] for n in order
                 if not gui.Handler._too_slow_to_recheck(n, decks[n["name"]])]
    picks = tractable[:3]
    canned = dict(zip(picks, [-3.0, 0.0, -7.0]))       # in-band, in-band, below the band

    def fake_edge(npc, entry, pool, cfg):
        v = canned.get(npc["name"])
        if v is None:
            return 8.0                                 # everyone else: clear win, no re-check
        return v + 5.0 if cfg is gui._SUGGEST_ACCURATE else v
    monkeypatch.setattr(gui, "_deck_edge", fake_edge)

    h = _Cap()
    h._suggest({"limit": 12, "budget": 999, "workers": 1})
    res = h.sent[1]
    rows = {r["name"]: r for r in res["suggestions"]}

    assert rows[picks[0]]["edgeKind"] == "accurate" and rows[picks[0]]["edge"] == 2.0
    assert rows[picks[1]]["edgeKind"] == "accurate" and rows[picks[1]]["edge"] == 5.0
    assert rows[picks[2]]["edgeKind"] == "screen" and rows[picks[2]]["edge"] == -7.0  # skipped
    assert res["rechecked"] == 2
    ranks = [gui._SUGGEST_BUCKET_RANK[r["bucket"]] for r in res["suggestions"]]
    assert ranks == sorted(ranks)                      # output ordered best-bucket first


def test_suggest_fast_skips_the_accurate_pass(_isolated, monkeypatch):
    monkeypatch.setattr(gui, "_owned_ids", lambda: [1, 2, 3, 4, 5])
    monkeypatch.setattr(gui, "_deck_edge", lambda npc, entry, pool, cfg: -1.0)
    h = _Cap()
    h._suggest({"limit": 6, "fast": True, "workers": 1})
    res = h.sent[1]
    assert res["rechecked"] == 0
    assert all(r["edgeKind"] == "screen" for r in res["suggestions"])
    assert all(r["bucket"] == "likely" for r in res["suggestions"])   # screen -1 -> likely
