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
from collections import Counter
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
    clean = _validate(rules)
    day = on or rule_day().isoformat()
    data["regions"][region] = {"rules": clean, "date": day}
    save_regional(data)
    log_observation(region, clean, day)       # regional.json only keeps today; this keeps all
    return data


def clear_regional(region: str) -> dict:
    data = load_regional()
    data["regions"].pop(region, None)
    save_regional(data)
    return data


def rule_day(when: datetime | None = None) -> date:
    """The *rule-day* containing ``when`` (default: now).

    Regionals roll at 15:00 UTC, so a rule-day runs 15:00 UTC to 15:00 UTC and is
    named after the date it starts on.  This is the unit to file observations
    under - a plain local ``date.today()`` splits one rule-day across two names
    (and merges two rule-days into one) depending on the observer's timezone and
    the hour they happened to look, which would scramble any pattern in the log.
    """
    now = when or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    return now.date() - (timedelta(0) if now.hour >= 15 else timedelta(days=1))


def is_stale(iso: str | None) -> bool:
    """True if a regional entry recorded on ``iso`` predates the current rule-day
    (i.e. it may no longer be current)."""
    if not iso:
        return True
    try:
        recorded = date.fromisoformat(iso)
    except ValueError:
        return True
    return recorded < rule_day()


# --- observation log: regional.json holds only "now", this holds every day ----
#
# regional.json is overwritten every time a region is recorded, so it can answer
# "what are the rules today" but never "is there a pattern".  Each observation is
# therefore also appended here, one JSON object per line.

def history_path():
    return paths.user_path("regional_history.jsonl")


def load_history() -> list[dict]:
    """Every logged observation, oldest first.  Unparseable lines are skipped."""
    p = history_path()
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("day") and rec.get("region"):
                out.append(rec)
    return out


def log_observation(region: str, rules: list[str], day: str | None = None,
                    *, recorded: str | None = None) -> bool:
    """Append one (rule-day, region, rules) observation.  Returns False without
    writing if the latest entry for that day and region already says the same
    thing, so re-recording an unchanged region does not inflate the sample.

    A *different* reading for a day already logged IS appended - it is a
    correction, and readers take the last entry for a (day, region) as the truth.
    """
    day = day or rule_day().isoformat()
    rules = list(rules)
    for rec in reversed(load_history()):
        if rec.get("day") == day and rec.get("region") == region:
            if list(rec.get("rules") or []) == rules:
                return False
            break
    p = history_path()
    paths.ensure_user_dir()
    rec = {"day": day, "region": region, "rules": rules,
           "recorded": recorded or datetime.now(timezone.utc)
           .replace(microsecond=0).isoformat()}
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return True


def seed_history() -> int:
    """One-off: fold whatever regional.json currently holds into an empty log, so
    days recorded before the log existed are not lost.  Returns rows added."""
    if load_history():
        return 0
    n = 0
    for region, ent in sorted((load_regional().get("regions") or {}).items()):
        if ent.get("rules") and ent.get("date"):
            n += log_observation(region, ent["rules"], ent["date"],
                                 recorded=ent["date"] + "T00:00:00+00:00")
    return n


def observations() -> dict[tuple[str, str], list[str]]:
    """``(day, region) -> rules``, keeping the last entry logged for each pair."""
    out: dict[tuple[str, str], list[str]] = {}
    for rec in load_history():
        out[(rec["day"], rec["region"])] = list(rec.get("rules") or [])
    return out


# --- pattern analysis --------------------------------------------------------
#
# Every function here reports its own sample size alongside its answer, because
# with a handful of days each one will happily produce a confident-looking number
# out of pure noise.  MIN_* are the points below which a result says nothing at
# all; they are deliberately conservative.

MIN_DAYS_PER_REGION = 10        # before per-region rule frequencies mean anything
MIN_CONSECUTIVE_PAIRS = 8       # before a repeat rate means anything


def by_region(obs) -> dict[str, list[tuple[str, list[str]]]]:
    """``region -> [(day, rules), ...]`` sorted by day."""
    out: dict[str, list[tuple[str, list[str]]]] = {}
    for (day, region), rules in obs.items():
        out.setdefault(region, []).append((day, rules))
    for rows in out.values():
        rows.sort()
    return out


def rule_frequency(obs) -> dict[str, Counter]:
    """``region -> Counter(rule -> days seen)``."""
    out: dict[str, Counter] = {}
    for region, rows in by_region(obs).items():
        c: Counter = Counter()
        for _day, rules in rows:
            c.update(rules)
        out[region] = c
    return out


def consecutive_pairs(obs) -> dict[str, list[tuple[list[str], list[str]]]]:
    """``region -> [(rules on day N, rules on day N+1), ...]`` for days actually
    observed back to back.  Gaps are skipped - you cannot compare across a day
    you never looked at."""
    out: dict[str, list[tuple[list[str], list[str]]]] = {}
    for region, rows in by_region(obs).items():
        pairs = []
        for (d1, r1), (d2, r2) in zip(rows, rows[1:]):
            if date.fromisoformat(d2) - date.fromisoformat(d1) == timedelta(days=1):
                pairs.append((r1, r2))
        if pairs:
            out[region] = pairs
    return out


def repeat_rate(obs) -> tuple[int, int]:
    """``(days that repeated the day before, consecutive pairs seen)`` across all
    regions.  A high rate would mean rules persist; near zero means they reroll."""
    same = total = 0
    for pairs in consecutive_pairs(obs).values():
        for r1, r2 in pairs:
            total += 1
            same += sorted(r1) == sorted(r2)
    return same, total


def weekday_counts(obs) -> dict[int, Counter]:
    """``weekday (0=Mon) -> Counter(rule)``, for a day-of-week pattern."""
    out: dict[int, Counter] = {}
    for (day, _region), rules in obs.items():
        out.setdefault(date.fromisoformat(day).weekday(), Counter()).update(rules)
    return out


def cross_region_agreement(obs) -> tuple[int, int]:
    """``(pairs of regions that matched, pairs compared)`` on days where two or
    more regions were observed.  Tests whether the game rolls once globally or
    once per region."""
    days: dict[str, list[list[str]]] = {}
    for (day, _region), rules in obs.items():
        days.setdefault(day, []).append(rules)
    same = total = 0
    for rules_seen in days.values():
        for i in range(len(rules_seen)):
            for j in range(i + 1, len(rules_seen)):
                total += 1
                same += sorted(rules_seen[i]) == sorted(rules_seen[j])
    return same, total


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
