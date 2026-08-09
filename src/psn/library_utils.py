import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

VALID_TITLE_ID = re.compile(
    r"^(CUSA|PPSA|PCSE|PCSA|NPWR|NPUA|NPUZ|NPHB|NPHG|NPHX|NPEA|NPEB|NPEZ|NPUF|NPUJ|NPUK|NPUH|NPUC|NPUV|NPUW|NPUY|NPUQ|NPUB|NPUG|NPUX|NPUZ)\d{5}_\d{2}$"
)

GENERIC_NAMES = frozenset(
    {
        "",
        "unknown",
        "unknown game",
        "untitled",
        "title",
    }
)

# Names marking a non-game product (soundtrack bundles, demos, themes) that
# shares a concept with the real game and must never represent it.
JUNK_NAME_RE = re.compile(
    r"soundtrack|\bost\b|\bdemo\b|\btrial\b|\btheme\b|\bavatar\b|\bbeta\b",
    re.IGNORECASE,
)


def is_junk_name(name: Optional[str]) -> bool:
    return bool(name and JUNK_NAME_RE.search(name))


def normalize_title(name: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (name or "").lower()).strip()


def is_valid_title_id(title_id: str) -> bool:
    return bool(title_id and VALID_TITLE_ID.match(title_id))


def pick_display_name(*candidates: Optional[str]) -> str:
    best = ""
    best_score = -1
    for candidate in candidates:
        if not candidate:
            continue
        name = candidate.strip()
        if name.lower() in GENERIC_NAMES:
            continue
        score = len(name)
        # A clean name always beats a junk one ("KNACK 2 + soundtrack").
        if is_junk_name(name):
            score -= 10_000
        if score > best_score:
            best = name
            best_score = score
    return best


def should_skip_played_entry(entry: Dict) -> bool:
    if entry.get("category") != "unknown":
        return False
    return not pick_display_name(
        entry.get("name"),
        entry.get("localizedName"),
        (entry.get("concept") or {}).get("name"),
    )


def merge_library_entries(entries: List[Dict[str, str]]) -> List[Dict[str, str]]:
    merged: Dict[str, Dict[str, str]] = {}
    for entry in entries:
        title_id = entry.get("titleId")
        if not title_id or not is_valid_title_id(title_id):
            continue
        if should_skip_played_entry(entry):
            continue

        name = pick_display_name(
            entry.get("name"),
            entry.get("localizedName"),
            (entry.get("concept") or {}).get("name"),
        )
        if not name:
            continue

        existing = merged.get(title_id)
        if existing:
            existing["name"] = pick_display_name(existing.get("name"), name)
            if entry.get("conceptId"):
                existing["conceptId"] = entry["conceptId"]
        else:
            merged[title_id] = {
                "titleId": title_id,
                "name": name,
                "conceptId": entry.get("conceptId"),
            }
    return list(merged.values())


def build_concept_siblings(played_games: List[Dict]) -> Dict[str, List[str]]:
    groups: Dict[str, set] = {}
    for title in played_games:
        if not isinstance(title, dict):
            continue
        concept = title.get("concept") or {}
        concept_id = concept.get("id")
        if concept_id is None:
            continue
        key = str(concept_id)
        group = groups.setdefault(key, set())
        title_id = title.get("titleId")
        if title_id:
            group.add(title_id)
        for alt_id in concept.get("titleIds") or []:
            if alt_id:
                group.add(alt_id)

    siblings: Dict[str, List[str]] = {}
    for ids in groups.values():
        ordered = sorted(ids)
        for title_id in ordered:
            siblings[title_id] = [other for other in ordered if other != title_id]
    return siblings


def alias_context_by_siblings(
    context: dict,
    game_ids: List[str],
    siblings: Dict[str, List[str]],
    *,
    has_data=None,
):
    """Copy stats from a sibling SKU when the requested title id has no data."""
    if has_data is None:
        has_data = bool
    for game_id in game_ids:
        if game_id in context and has_data(context[game_id]):
            continue
        for sibling_id in siblings.get(game_id, []):
            sibling_value = context.get(sibling_id)
            if sibling_value and has_data(sibling_value):
                context[game_id] = sibling_value
                break


def parse_iso_datetime(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())
