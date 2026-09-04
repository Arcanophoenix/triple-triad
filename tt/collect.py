"""Import an FFXIV Collect account export, and track which NPCs you have beaten.

The export (ffxivcollect.com -> your character -> Export) is a single JSON object
of id lists, of which two matter here::

    {"cards": [1, 7, 23, ...], "npcs": [2293762, ...], ...}

**Both lists are FFXIV Collect's own ids, and neither is any id we assign.**

``cards`` are Collect's card ids - the number in a ``ffxivcollect.com/triad/cards/<id>``
link, stored per card in ``data/cards.json`` as ``collect_id``.  It is NOT the
in-game "No." (= our ``Card.number``): the two happen to agree for roughly the
first 60 cards and then diverge - Collect slots the 15 FF-collab cards in at
ids 61-75, so every card after that is offset.  Mapping through ``Card.number``
imported the wrong card for anything past the low 60s (Collect id 64 is Gaius
van Baelsar, not our No. 64); it now goes through ``collect_id``.

``npcs`` are Collect's NPC ids (7 digits, from ``/triad/npcs/<id>``), stored per
NPC in ``data/npcs.json`` as ``collect_id``.  133 of our 134 NPCs have one -
**Lewena is absent from FFXIV Collect entirely**, so she can never arrive through
an import and has to be ticked by hand.

Beaten NPCs live in ``collection.json`` under ``npcs_beaten`` as a list of names,
matching how ``owned`` stores card names rather than ids.

A second source feeds the same ``collect_id`` fields: a native export straight
from the game client (see the companion Dalamud plugin under
``scripts/dalamud/``, which reads the game's own memory - no FFXIV Collect
account needed). It turns out **Collect doesn't invent its own numbering for
either list** - both ``collect_id`` fields already ARE the game's native Excel
sheet row ids verbatim: confirmed for NPCs by cross-checking Memeroon's real
``TripleTriad`` sheet row (2293762), and for cards by comparing all 475
``TripleTriadCard`` sheet row ids against every card's ``collect_id`` by name -
zero mismatches. So a native export needs no separate id mapping at all;
``map_cards``/``map_npcs`` already do the right thing, and
:func:`apply_native_export` is a thin, differently-shaped front door onto the
same :func:`apply_export` machinery.
"""
from __future__ import annotations

import json
from pathlib import Path

from tt.data import CARDS, load_npcs, read_collection, write_collection



def load_export(path: str | Path) -> dict:
    """Parse an export file, with errors phrased for someone who picked the wrong
    file rather than as a traceback."""
    p = Path(path).expanduser()
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"cannot read {p}: {e}") from None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"{p.name} is not valid JSON ({e})") from None
    if not isinstance(data, dict) or not ({"cards", "npcs"} & set(data)):
        raise ValueError(f"{p.name} has no 'cards' or 'npcs' list - is it an "
                         f"FFXIV Collect export?")
    return data


def _card_by_collect_id() -> dict[int, object]:
    return {c.collect_id: c for c in CARDS if c.collect_id}


def _npc_by_collect_id() -> dict[int, str]:
    return {n["collect_id"]: n["name"] for n in load_npcs() if n.get("collect_id")}


def map_cards(ids) -> tuple[list[str], list[int]]:
    """``(card names, ids we could not place)``."""
    by_cid = _card_by_collect_id()
    names, unknown = [], []
    for i in ids or []:
        c = by_cid.get(i)
        (names.append(c.name) if c else unknown.append(i))
    return names, unknown


def map_npcs(ids) -> tuple[list[str], list[int]]:
    """``(npc names, ids we could not place)``."""
    by_id = _npc_by_collect_id()
    names, unknown = [], []
    for i in ids or []:
        n = by_id.get(i)
        (names.append(n) if n else unknown.append(i))
    return names, unknown


def load_beaten() -> set[str]:
    return set(read_collection().get("npcs_beaten") or [])


def save_beaten(names) -> list[str]:
    col = read_collection()
    col["npcs_beaten"] = sorted(set(names))
    write_collection(col)
    return col["npcs_beaten"]


def set_beaten(name: str, beaten: bool) -> list[str]:
    """Tick or untick one NPC by name (validated against the roster)."""
    known = {n["name"] for n in load_npcs()}
    if name not in known:
        raise ValueError(f"unknown NPC {name!r}")
    cur = load_beaten()
    cur.add(name) if beaten else cur.discard(name)
    return save_beaten(cur)


def apply_export(data: dict, *, replace: bool = False) -> dict:
    """Fold an export into collection.json and report what happened.

    Merges by default rather than replacing: cards and wins are only ever gained,
    so a union cannot lose anything you recorded by hand, while a replace would
    silently drop cards you ticked in the GUI but have not re-exported.  Pass
    ``replace=True`` to make the export authoritative instead.
    """
    card_names, bad_cards = map_cards(data.get("cards"))
    npc_names, bad_npcs = map_npcs(data.get("npcs"))

    col = read_collection()
    before_cards = set(col.get("owned") or [])
    before_npcs = set(col.get("npcs_beaten") or [])
    after_cards = set(card_names) if replace else before_cards | set(card_names)
    after_npcs = set(npc_names) if replace else before_npcs | set(npc_names)

    col["owned"] = sorted(after_cards)
    col["npcs_beaten"] = sorted(after_npcs)
    write_collection(col)
    return {
        "cards_added": sorted(after_cards - before_cards),
        "cards_removed": sorted(before_cards - after_cards),
        "cards_total": len(after_cards),
        "npcs_added": sorted(after_npcs - before_npcs),
        "npcs_removed": sorted(before_npcs - after_npcs),
        "npcs_total": len(after_npcs),
        "unknown_card_ids": bad_cards,
        "unknown_npc_ids": bad_npcs,
    }


def unimportable_npcs() -> list[str]:
    """NPCs with no Collect id, so an import can never tick them."""
    return sorted(n["name"] for n in load_npcs() if not n.get("collect_id"))


def load_native_export(path: str | Path) -> dict:
    """Parse a native-export file (from the companion Dalamud plugin), with
    errors phrased for someone who picked the wrong file rather than a
    traceback."""
    p = Path(path).expanduser()
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"cannot read {p}: {e}") from None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"{p.name} is not valid JSON ({e})") from None
    if not isinstance(data, dict) or not ({"owned_card_ids", "beaten_npc_ids"} & set(data)):
        raise ValueError(f"{p.name} has no 'owned_card_ids' or 'beaten_npc_ids' list - "
                         f"is it a native client export?")
    return data


def apply_native_export(data: dict, *, replace: bool = False) -> dict:
    """Fold a native client export into collection.json.

    Just :func:`apply_export` under its own key names
    (``owned_card_ids``/``beaten_npc_ids`` instead of ``cards``/``npcs``) - the
    ids are the same native sheet row ids either way, see module docstring.
    """
    return apply_export(
        {"cards": data.get("owned_card_ids"), "npcs": data.get("beaten_npc_ids")},
        replace=replace,
    )
