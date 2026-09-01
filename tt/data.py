"""Card database and loose name resolution.

``cards.json`` (from scripts/extract_wiki.py) is the source of truth for card
stats.  Cards get a stable integer ``id`` = their index in :data:`CARDS`; that id
is what boards and hands store.
"""
from __future__ import annotations

import itertools
import json
import re
from dataclasses import dataclass

from tt import paths


@dataclass(frozen=True, slots=True)
class Card:
    id: int
    number: int
    series: str        # "main" | "ff"
    name: str
    stars: int
    kind: str          # "None" | "Primal" | "Scion" | "Garlean" | "Society"
    sides: tuple       # (N, E, S, W), each 1..10  (10 == 'A')

    @property
    def high(self) -> str:
        return "/".join("A" if v == 10 else str(v) for v in self.sides)


CARDS: list[Card] = []
_BY_NORM: dict[str, Card] = {}


def _norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"\bcard\b", "", s)
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def _load() -> None:
    raw = json.loads((paths.BUNDLED_DATA / "cards.json").read_text(encoding="utf-8"))
    CARDS.clear()
    _BY_NORM.clear()
    for i, c in enumerate(raw):
        s = c["sides"]
        card = Card(i, c["number"], c["series"], c["name"], c["stars"], c["type"],
                    (s["up"], s["right"], s["down"], s["left"]))
        CARDS.append(card)
        _BY_NORM.setdefault(_norm(card.name), card)


_load()


def register_test_card(sides, kind: str = "None", name: str | None = None) -> Card:
    """Append a synthetic card with explicit sides and return it (tests only)."""
    i = len(CARDS)
    c = Card(i, -1, "test", name or f"T{i}", 1, kind, tuple(sides))
    CARDS.append(c)
    return c


def resolve(q: str) -> Card:
    """Resolve loose input to a Card: 'ifrit', 'Ifrit Card', '62', '*3', 'ultros typhon'."""
    raw = str(q).strip()
    if raw.startswith("*") and raw[1:].isdigit():
        for c in CARDS:
            if c.series == "ff" and c.number == int(raw[1:]):
                return c
    n = _norm(raw)
    if n in _BY_NORM:
        return _BY_NORM[n]
    if raw.isdigit():
        for c in CARDS:
            if c.series == "main" and c.number == int(raw):
                return c
    subs = [c for k, c in _BY_NORM.items() if n and n in k]
    if len(subs) == 1:
        return subs[0]
    if not subs:
        raise KeyError(f"no card matches {q!r}")
    opts = ", ".join(sorted(c.name for c in subs)[:12])
    raise KeyError(f"{q!r} is ambiguous: {opts}")


def load_npcs() -> list[dict]:
    p = paths.BUNDLED_DATA / "npcs.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def load_decks() -> dict:
    """Recorded NPC decks: the bundled set, then any user-recorded overrides.

    The overlay only applies to a frozen app -- in a source checkout the bundled
    file *is* the user file, so this is just a plain read of data/decks.json.
    """
    decks: dict = {}
    b = paths.BUNDLED_DATA / "decks.json"
    if b.is_file():
        decks.update(json.loads(b.read_text(encoding="utf-8")))
    u = paths.user_path("decks.json")
    if paths.FROZEN and u.is_file():
        decks.update(json.loads(u.read_text(encoding="utf-8")))
    return decks


def save_decks(decks: dict) -> None:
    if paths.FROZEN:
        paths.ensure_user_dir()
        target = paths.user_path("decks.json")
    else:
        target = paths.BUNDLED_DATA / "decks.json"
    target.write_text(json.dumps(decks, indent=2, ensure_ascii=False) + "\n")


def is_variable_deck(entry: dict) -> bool:
    """True if the NPC draws a random subset of a pool (fixed + pool schema)."""
    return bool(entry) and not entry.get("cards") and bool(entry.get("pool"))


def deck_draw(entry: dict) -> int:
    """How many cards the NPC draws from its pool (0 for a fixed deck)."""
    if not is_variable_deck(entry):
        return 0
    return int(entry.get("draw", 5 - len(entry.get("fixed", []))))


def npc_deck_options(entry: dict) -> list[list[str]]:
    """Every concrete 5-card deck an NPC entry can field, as card-name lists.

    A fixed deck yields one option; a variable deck yields C(pool, draw) of them.
    """
    if entry.get("cards"):
        return [list(entry["cards"])]
    if not is_variable_deck(entry):
        return []
    fixed = list(entry.get("fixed", []))
    pool = list(entry.get("pool", []))
    draw = deck_draw(entry)
    return [fixed + list(extra) for extra in itertools.combinations(pool, draw)]


# The five 1-star cards every player is given when Triple Triad is unlocked.
STARTER_CARDS = ["Dodo Card", "Sabotender Card", "Bomb Card", "Mandragora Card", "Coeurl Card"]


def read_collection() -> dict:
    """collection.json exactly as stored - no defaults applied, unknown keys kept.

    ``load_collection`` normalises for readers (starters folded in, decks
    defaulted) and so cannot be written back; anything that *edits* the file must
    go through this instead or it will drop keys it did not know about."""
    p = paths.user_path("collection.json")
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_collection(col: dict) -> None:
    paths.ensure_user_dir()
    paths.user_path("collection.json").write_text(
        json.dumps(col, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_collection() -> dict:
    p = paths.user_path("collection.json")
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    owned = set(data.get("owned", [])) | set(STARTER_CARDS)
    decks = {"starter": list(STARTER_CARDS), **data.get("decks", {})}
    return {"owned": sorted(owned), "decks": decks}


def find_npc(q: str, npcs: list[dict] | None = None) -> dict:
    npcs = npcs if npcs is not None else load_npcs()
    n = q.lower().strip()
    exact = [x for x in npcs if x["name"].lower() == n]
    if exact:
        return exact[0]
    subs = [x for x in npcs if n in x["name"].lower()]
    if len(subs) == 1:
        return subs[0]
    if not subs:
        raise KeyError(f"no NPC matches {q!r}")
    raise KeyError(f"{q!r} is ambiguous: " + ", ".join(x["name"] for x in subs[:12]))
