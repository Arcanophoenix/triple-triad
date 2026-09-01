"""Regional Triple Triad rules.

An NPC match runs up to two *match rules* (fixed, intrinsic to the NPC) plus up
to two *regional rules* (vary by area, reset daily at 15:00 UTC).  ``data/`` now
stores only each NPC's match rules; the regional half is tracked here, per region,
in a small user-editable file (``regional.json``) and unioned onto the match
rules at solve time.

The zone -> region grouping below is a best effort - the in-game Match
Registration screen is authoritative.  If two NPCs the map calls one region show
different regional rules, split the region here.  ``FIXED`` marks spots whose
NPCs ignore regional rules entirely (the Gold Saucer, the Battlehall, ...).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from tt import paths
from tt.model import RuleSet

FIXED = "(fixed rules)"

REGIONS: tuple[str, ...] = (
    "La Noscea",
    "The Black Shroud",
    "Thanalan",
    "Coerthas and Mor Dhona",
    "Abalathia",
    "Dravania",
    "Gyr Abania",
    "Othard",
    "Norvrandt",
    "Ilsabard",
    "Tural",
)

_ZONE_REGION: dict[str, str] = {
    # --- La Noscea ---
    "Limsa Lominsa Upper Decks": "La Noscea",
    "Limsa Lominsa Lower Decks": "La Noscea",
    "Middle La Noscea": "La Noscea",
    "Lower La Noscea": "La Noscea",
    "Eastern La Noscea": "La Noscea",
    "Western La Noscea": "La Noscea",
    "Upper La Noscea": "La Noscea",
    "Outer La Noscea": "La Noscea",
    "Mist": "La Noscea",
    # --- The Black Shroud ---
    "New Gridania": "The Black Shroud",
    "Old Gridania": "The Black Shroud",
    "Central Shroud": "The Black Shroud",
    "East Shroud": "The Black Shroud",
    "South Shroud": "The Black Shroud",
    "North Shroud": "The Black Shroud",
    "The Lavender Beds": "The Black Shroud",
    # --- Thanalan ---
    "Ul'dah - Steps of Nald": "Thanalan",
    "Ul'dah - Steps of Thal": "Thanalan",
    "Western Thanalan": "Thanalan",
    "Central Thanalan": "Thanalan",
    "Eastern Thanalan": "Thanalan",
    "Southern Thanalan": "Thanalan",
    "Northern Thanalan": "Thanalan",
    "The Goblet": "Thanalan",
    # --- Coerthas and Mor Dhona (incl. Ishgard) ---
    "Coerthas Central Highlands": "Coerthas and Mor Dhona",
    "Coerthas Western Highlands": "Coerthas and Mor Dhona",
    "Mor Dhona": "Coerthas and Mor Dhona",
    "Foundation": "Coerthas and Mor Dhona",
    "The Pillars": "Coerthas and Mor Dhona",
    "Fortemps Manor": "Coerthas and Mor Dhona",
    # --- Abalathia's Spine ---
    "The Sea of Clouds": "Abalathia",
    "Azys Lla": "Abalathia",
    # --- Dravania ---
    "The Dravanian Forelands": "Dravania",
    "The Dravanian Hinterlands": "Dravania",
    "The Churning Mists": "Dravania",
    "Idyllshire": "Dravania",
    "Tailfeather": "Dravania",
    # --- Gyr Abania ---
    "Rhalgr's Reach": "Gyr Abania",
    "The Fringes": "Gyr Abania",
    "The Peaks": "Gyr Abania",
    "The Lochs": "Gyr Abania",
    # --- Othard / Hingashi ---
    "Kugane": "Othard",
    "The Ruby Sea": "Othard",
    "Yanxia": "Othard",
    "The Azim Steppe": "Othard",
    "The Doman Enclave": "Othard",
    # --- Norvrandt ---
    "The Crystarium": "Norvrandt",
    "Eulmore": "Norvrandt",
    "Lakeland": "Norvrandt",
    "Kholusia": "Norvrandt",
    "Amh Araeng": "Norvrandt",
    "Il Mheg": "Norvrandt",
    "The Rak'tika Greatwood": "Norvrandt",
    "The Tempest": "Norvrandt",
    "Terncliff": "Norvrandt",
    # --- Ilsabard and the North ---
    "Old Sharlayan": "Ilsabard",
    "Radz-at-Han": "Ilsabard",
    "Labyrinthos": "Ilsabard",
    "Thavnair": "Ilsabard",
    "Garlemald": "Ilsabard",
    "Mare Lamentorum": "Ilsabard",
    "Ultima Thule": "Ilsabard",
    "Elpis": "Ilsabard",
    # --- Tural ---
    "Tuliyollal": "Tural",
    "Solution Nine": "Tural",
    "Urqopacha": "Tural",
    "Kozama'uka": "Tural",
    "Yak T'el": "Tural",
    "Shaaloani": "Tural",
    "Heritage Found": "Tural",
    "Living Memory": "Tural",
    "Zirgorteh the Open-armed": "Tural",
    # --- regional rules do not apply here ---
    "The Gold Saucer": FIXED,
    "The Battlehall": FIXED,
    "Lower Jeuno": FIXED,
    "Gangos": FIXED,
}


def region_for_zone(zone: str | None) -> str | None:
    """Region name, ``FIXED`` for regional-immune spots, or ``None`` if the zone
    isn't in the map (caller should treat that as 'no regional rules known')."""
    if not zone:
        return None
    return _ZONE_REGION.get(zone.strip())


def region_for_npc(npc: dict) -> str | None:
    return region_for_zone((npc.get("location") or {}).get("zone"))


# --- regional.json: {"regions": {<region>: {"rules": [...], "date": "YYYY-MM-DD"}}} ---

def _path():
    return paths.user_path("regional.json")


def load_regional() -> dict:
    b = paths.BUNDLED_DATA / "regional.json"
    data: dict = {"regions": {}}
    if b.is_file():
        try:
            data = json.loads(b.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    u = _path()
    if paths.FROZEN and u.is_file():
        try:
            data = json.loads(u.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    data.setdefault("regions", {})
    return data


def save_regional(data: dict) -> None:
    target = _path() if paths.FROZEN else (paths.BUNDLED_DATA / "regional.json")
    if paths.FROZEN:
        paths.ensure_user_dir()
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def regional_rules(region: str | None) -> tuple[list[str], str | None]:
    """``(rule names, date they were recorded)`` for a region.  ``([], None)`` for
    an unknown region or a ``FIXED`` (regional-immune) spot."""
    if not region or region == FIXED:
        return [], None
    ent = load_regional()["regions"].get(region) or {}
    return list(ent.get("rules") or []), ent.get("date")


def _validate(rules: list[str]) -> list[str]:
    clean = [r.strip() for r in rules if r and r.strip()]
    RuleSet.from_names(clean)                 # raises on an unknown rule name
    return clean


def set_regional(region: str, rules: list[str], on: str | None = None) -> dict:
    if region not in REGIONS:
        raise ValueError(f"unknown region {region!r}; one of: {', '.join(REGIONS)}")
    data = load_regional()
    data["regions"][region] = {"rules": _validate(rules),
                               "date": on or date.today().isoformat()}
    save_regional(data)
    return data


def clear_regional(region: str) -> dict:
    data = load_regional()
    data["regions"].pop(region, None)
    save_regional(data)
    return data


def is_stale(iso: str | None) -> bool:
    """True if a regional entry recorded on ``iso`` predates the most recent
    15:00 UTC daily reset (i.e. it may no longer be current)."""
    if not iso:
        return True
    try:
        recorded = date.fromisoformat(iso)
    except ValueError:
        return True
    now = datetime.now(timezone.utc)
    last_reset = now.date() - (timedelta(0) if now.hour >= 15 else timedelta(days=1))
    return recorded < last_reset


def combine(match_rules, regional: list[str]) -> list[str]:
    """Match rules first, then regional, de-duplicated case-insensitively."""
    seen, out = set(), []
    for r in list(match_rules) + list(regional):
        r = (r or "").strip()
        if r and r.lower() not in seen:
            seen.add(r.lower())
            out.append(r)
    return out


def effective_rules(npc: dict, *, deck_entry: dict | None = None,
                    override=None, use_regional: bool = True) -> list[str]:
    """Rule names for a match against ``npc``.

    An explicit ``override`` (list or comma string) wins verbatim.  Otherwise the
    NPC's match rules - a recorded deck entry's ``rules`` beat the roster's - are
    unioned with the current regional rules for the NPC's region, unless
    ``use_regional`` is False.
    """
    if override:
        parts = override.split(",") if isinstance(override, str) else override
        return [r.strip() for r in parts if r and r.strip()]
    match = (deck_entry or {}).get("rules") or npc.get("rules") or []
    if not use_regional:
        return list(match)
    reg, _date = regional_rules(region_for_npc(npc))
    return combine(match, reg)
