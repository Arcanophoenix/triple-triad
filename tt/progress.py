"""Which NPCs the player can actually reach yet.

"Who should I challenge next" is useless if half the list is behind main-story
progress: an NPC in Old Sharlayan is not an option for someone still in La
Noscea, however winnable the matchup looks.

**The gate is the NPC's patch, not their zone.**  That looks like the weaker
signal and is in fact the stronger one.  An NPC cannot stand in a zone that did
not exist when they were added, so their patch is always at least as late as
their zone's expansion - checked against the whole roster, every single
zone/patch disagreement had the patch later, never the zone.  The patch
additionally catches the NPCs who stand in an early zone but arrived with much
later content, which a zone map cannot see at all: Ylaire is in Old Gridania but
came in 6.5, Kilfufu is in Ul'dah but came in 6.25, Droyn in Ul'dah at 5.45.
Gating those on "is Ul'dah reachable" would offer a brand-new player NPCs that
are many expansions away.

It also means this needs no zone table of its own.  ``tt.regions`` has one, but
it groups zones for *regional rules* - where Ishgard genuinely does share a
region with Mor Dhona - and reusing it here would call Ishgard's NPCs reachable
in A Realm Reborn.  Two different questions, deliberately two different maps.

Progress is stored in ``collection.json`` under ``progress`` as a patch number.
"""
from __future__ import annotations

from tt.data import read_collection, write_collection

# expansion short name -> major patch version, in release order
EXPANSIONS: tuple[tuple[str, int], ...] = (
    ("ARR", 2), ("HW", 3), ("SB", 4), ("ShB", 5), ("EW", 6), ("DT", 7),
)
_BY_MAJOR = {major: name for name, major in EXPANSIONS}
_ALIASES = {
    "arr": 2, "a realm reborn": 2, "realm reborn": 2,
    "hw": 3, "heavensward": 3,
    "sb": 4, "stormblood": 4,
    "shb": 5, "shadowbringers": 5,
    "ew": 6, "endwalker": 6,
    "dt": 7, "dawntrail": 7,
}


def npc_patch(npc: dict) -> float | None:
    """The patch that added this NPC, as a comparable number.

    Patch strings compare correctly as floats here because they are all at most
    two decimal places (4.45 < 4.5 < 4.55, 7.5 < 7.51)."""
    raw = str(npc.get("patch") or "").strip()
    try:
        return float(raw)
    except ValueError:
        return None


def expansion_of(patch: float | None) -> str | None:
    return None if patch is None else _BY_MAJOR.get(int(patch))


def parse_progress(text: str | float | None) -> float | None:
    """Accept an expansion name or a patch number.

    An expansion name means "I have finished that expansion's content", so it
    maps to the end of that expansion (``ShB`` -> 5.99) rather than its start -
    otherwise finishing Shadowbringers would still hide every 5.x NPC.  Give a
    patch number instead when you want to be exact about mid-expansion progress.
    """
    if text is None or text == "":
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip().lower()
    if s in _ALIASES:
        return _ALIASES[s] + 0.99
    try:
        return float(s)
    except ValueError:
        names = ", ".join(n for n, _ in EXPANSIONS)
        raise ValueError(f"unknown progress {text!r}; give a patch number "
                         f"(e.g. 6.3) or one of: {names}")


def describe(progress: float | None) -> str:
    if progress is None:
        return "not set"
    exp = expansion_of(progress)
    # x.99 is what an expansion name parses to; show it back the same way
    if abs(progress - (int(progress) + 0.99)) < 1e-9:
        return f"all of {exp}"
    return f"patch {progress:g} ({exp})"


def load_progress() -> float | None:
    """The recorded story progress, or None if the player never set it."""
    return parse_progress(read_collection().get("progress"))


def save_progress(text: str | float | None) -> float | None:
    """Record progress (or clear it with None).  Other keys are left alone -
    collection.json also holds the card collection and saved decks."""
    value = parse_progress(text)
    col = read_collection()
    if value is None:
        col.pop("progress", None)
    else:
        col["progress"] = value
    write_collection(col)
    return value


def is_reachable(npc: dict, progress: float | None) -> bool:
    """Whether the player can challenge this NPC yet.  Unknown progress means no
    filtering (everything is offered); an NPC with no patch recorded is assumed
    reachable rather than silently hidden."""
    if progress is None:
        return True
    p = npc_patch(npc)
    return True if p is None else p <= progress + 1e-9
