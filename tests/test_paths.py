"""tt.paths must be a no-op in a source checkout and honour TRIPLE_TRIAD_HOME."""
import importlib
import pathlib

import tt.paths as paths

REPO = pathlib.Path(__file__).resolve().parents[1]


def test_source_tree_is_unchanged():
    assert paths.FROZEN is False
    assert paths.RESOURCE_ROOT == REPO
    assert paths.BUNDLED_DATA == REPO / "data"
    # writable files land in the same data/ dir the tool always used
    assert paths.USER_DIR == REPO / "data"
    assert paths.user_path("collection.json") == REPO / "data" / "collection.json"


def test_home_override(monkeypatch, tmp_path):
    monkeypatch.setenv("TRIPLE_TRIAD_HOME", str(tmp_path))
    reloaded = importlib.reload(paths)
    try:
        assert reloaded.USER_DIR == tmp_path
        assert reloaded.user_path("history.jsonl") == tmp_path / "history.jsonl"
        # resources still come from the checkout, not the override
        assert reloaded.BUNDLED_DATA == REPO / "data"
    finally:
        monkeypatch.delenv("TRIPLE_TRIAD_HOME", raising=False)
        importlib.reload(paths)


def test_decks_still_readable_through_data_module():
    from tt.data import load_decks
    decks = load_decks()
    assert isinstance(decks, dict) and decks, "bundled decks.json should load"
