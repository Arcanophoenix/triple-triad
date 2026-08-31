import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import difficulty as D  # noqa: E402


def test_patch_norm_spans_arr_to_current():
    assert D._patch_norm("2.0") == 0.0
    assert D._patch_norm("7.5") == 1.0
    assert 0.0 < D._patch_norm("5.0") < 1.0
    assert D._patch_norm(None) == 0.0


def test_rules_adjustment_direction():
    assert D._rules_adj(["All Open"]) < 0                 # you see their hand -> easier
    assert D._rules_adj(["Chaos"]) > 0                    # variance -> harder
    assert D._rules_adj(["Plus", "Same"]) > D._rules_adj(["Plus"])


def test_score_and_tier_ordering():
    easy = {"mgp_win": 15, "rewards": [], "patch": "2.0", "rules": ["All Open"]}
    brutal = {"mgp_win": 130, "rewards": [], "patch": "5.0", "rules": ["Chaos", "Swap"]}
    se, sb = D.score(easy), D.score(brutal)
    assert 0 <= se < sb <= 100
    assert D.tier(se) in ("intro", "easy")
    assert D.tier(sb) == "brutal"
    # tier() covers the whole range
    assert {D.tier(x) for x in range(0, 101, 5)} == {"intro", "easy", "moderate", "hard", "brutal"}


def test_edge_text_buckets():
    assert "win" in D._edge_txt(8)
    assert "coin-flip" in D._edge_txt(0)
    assert "better cards" in D._edge_txt(-4)
    assert D._edge_txt(None) == ""


def test_real_npcs_score_in_range_and_master_is_easy():
    from tt.data import load_npcs
    npcs = load_npcs()
    scores = {n["name"]: D.score(n) for n in npcs}
    assert all(0 <= s <= 100 for s in scores.values())
    assert scores["Triple Triad Master"] < scores["Lewena"]
