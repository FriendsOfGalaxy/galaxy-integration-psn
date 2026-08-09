import asyncio
import base64
import json
import logging
import time
import zlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import aiohttp
from galaxy.api.errors import (
    AccessDenied,
    AuthenticationRequired,
    BackendError,
    BackendNotAvailable,
    BackendTimeout,
    NetworkError,
    TooManyRequests,
    UnknownBackendResponse,
)
from galaxy.api.types import Achievement, GameTime, SubscriptionGame, UserInfo

from psn.constants import (
    ACCOUNT_ME_URL,
    DEFAULT_PAGE_SIZE,
    FRIENDS_PAGE_SIZE,
    LIBRARY_SOURCE_MEMO_TTL,
    PLAYED_GAMES_PAGE_SIZE,
    PSN_PLUS_SUBSCRIPTIONS_URL,
    STORE_TROPHY_BATCH_SIZE,
    STORE_TROPHY_NEGATIVE_TTL,
    TROPHY_FETCH_CONCURRENCY,
    TROPHY_TITLES_PAGE_SIZE,
)
from psn.duration import parse_play_duration
from psn.graphql import played_games_url, purchased_games_url
from psn.library_utils import (
    alias_context_by_siblings,
    build_concept_siblings,
    merge_library_entries,
    normalize_title,
    parse_iso_datetime,
    pick_display_name,
)
from psn.parsers import PSNGamesParser
from psn.trophies import extract_store_title_mappings, merge_earned_with_definitions
from psn.rest_urls import (
    friends_url,
    played_games_url as rest_played_games_url,
    profile_url as rest_profile_url,
    title_trophies_url,
    trophy_titles_url,
    user_trophies_earned_url,
    user_trophies_for_titles_url,
)

logger = logging.getLogger(__name__)

STORE_TITLE_PREFIXES = ("CUSA", "PPSA", "PCSE", "PCSA")

# persistent_cache keys (bump the suffix when the stored shape changes)
CACHE_PURCHASED = "purchased_v1"
CACHE_PLAYED = "played_v1"
CACHE_TROPHY_TITLES = "trophy_titles_v1"
CACHE_TROPHIES = "trophies_v1"
CACHE_STORE_TROPHY_MAP = "store_trophy_map_v1"
CACHE_LIBRARY = "library_v1"

# Galaxy's persistent cache stores strings; compressing large values raises
# the effective capacity ~4-5x so trophy caches for huge libraries fit.
CACHE_COMPRESS_THRESHOLD = 4096
CACHE_COMPRESS_PREFIX = "z:"


FRIENDS_PROFILE_BATCH = 8

# Errors where the fetch outcome is unknown: re-raise so Galaxy reports a
# per-game failure and retries next sync, instead of recording "no trophies".
TRANSIENT_TROPHY_ERRORS = (
    AccessDenied,
    AuthenticationRequired,
    BackendError,
    BackendNotAvailable,
    BackendTimeout,
    NetworkError,
    TooManyRequests,
    TimeoutError,
    aiohttp.ClientError,
)


@dataclass
class AchievementsContext:
    """Shared indexes for per-game trophy import (fetch happens in get_unlocked_achievements)."""

    concept_siblings: Dict[str, List[str]] = field(default_factory=dict)
    trophy_title_index: Dict[str, Dict[str, str]] = field(default_factory=dict)
    cache: Dict[str, List[Achievement]] = field(default_factory=dict)
    games_with_trophies: int = 0
    games_empty: int = 0
    total_unlocked: int = 0


class PSNClient:
    def __init__(self, http_client):
        self._http_client = http_client
        self._played_games_cache: Optional[List[Dict[str, Any]]] = None
        self._account_id: Optional[str] = None
        self._own_profile_cache: Optional[Dict[str, Any]] = None
        self._trophy_title_index: Dict[str, Dict[str, str]] = {}
        self._concept_siblings: Dict[str, List[str]] = {}
        self._trophy_semaphore = asyncio.Semaphore(TROPHY_FETCH_CONCURRENCY)
        self._persistent_cache: Optional[Callable[[], dict]] = None
        self._push_cache: Optional[Callable[[], None]] = None
        self._cache_dirty = False
        self._trophy_cache: Optional[Dict[str, dict]] = None
        self._store_trophy_map: Optional[Dict[str, Any]] = None
        self._purchased_memo: Optional[Tuple[float, List[Dict[str, str]]]] = None
        self._trophy_titles_memo: Optional[Tuple[float, List[Dict[str, str]]]] = None
        self._owned_ids: set = set()

    def attach_persistent_cache(
        self, getter: Callable[[], dict], pusher: Callable[[], None]
    ):
        """Wire Galaxy's persistent_cache so syncs survive Sony API outages."""
        self._persistent_cache = getter
        self._push_cache = pusher

    def _cache_load(self, key: str, default):
        if self._persistent_cache is None:
            return default
        try:
            raw = self._persistent_cache().get(key)
            if not raw:
                return default
            if isinstance(raw, str) and raw.startswith(CACHE_COMPRESS_PREFIX):
                raw = zlib.decompress(
                    base64.b64decode(raw[len(CACHE_COMPRESS_PREFIX) :])
                ).decode("utf-8")
            return json.loads(raw)
        except Exception:
            logger.warning("Could not read persistent cache key %s", key, exc_info=True)
            return default

    def _cache_store(self, key: str, value):
        if self._persistent_cache is None:
            return
        try:
            raw = json.dumps(value, separators=(",", ":"))
            if len(raw) > CACHE_COMPRESS_THRESHOLD:
                raw = CACHE_COMPRESS_PREFIX + base64.b64encode(
                    zlib.compress(raw.encode("utf-8"))
                ).decode("ascii")
            self._persistent_cache()[key] = raw
            self._cache_dirty = True
        except Exception:
            logger.warning("Could not write persistent cache key %s", key, exc_info=True)

    def flush_cache(self):
        if self._cache_dirty and self._push_cache is not None:
            try:
                self._push_cache()
            except Exception:
                logger.warning("Could not push persistent cache", exc_info=True)
            else:
                self._cache_dirty = False

    def set_account_id(self, account_id: str):
        self._account_id = str(account_id)

    async def _get_account_id(self) -> str:
        if not self._account_id:
            account = await self._http_client.api_get(ACCOUNT_ME_URL)
            self._account_id = str(account["accountId"])
        return self._account_id

    async def get_own_profile(self) -> Dict[str, Any]:
        # The userProfile API rejects the literal "me" ("Bad Request (path:
        # accountId)"); it needs the numeric account id.
        if self._own_profile_cache is None:
            account_id = await self._get_account_id()
            self._own_profile_cache = await self._http_client.api_get(
                rest_profile_url(account_id)
            )
        return self._own_profile_cache

    async def get_own_user_info(self) -> Tuple[str, str]:
        account_id = await self._get_account_id()
        profile = await self.get_own_profile()
        try:
            return account_id, profile["onlineId"]
        except (KeyError, TypeError) as exc:
            raise UnknownBackendResponse(str(exc)) from exc

    async def get_psplus_status(self) -> bool:
        try:
            profile = await self.get_own_profile()
            return bool(profile["isPlus"])
        except Exception:
            logger.warning(
                "Could not determine PS Plus status (profile API unavailable)",
                exc_info=True,
            )
            return False

    async def get_subscription_games(self) -> List[SubscriptionGame]:
        response = await self._http_client.get(
            PSN_PLUS_SUBSCRIPTIONS_URL,
            get_json=False,
            silent=True,
        )
        try:
            return PSNGamesParser().parse(response)
        except Exception as exc:
            logger.exception("Cannot parse subscription games")
            raise UnknownBackendResponse(str(exc)) from exc

    @staticmethod
    def _parse_purchased(response) -> List[Dict[str, str]]:
        try:
            data = (response or {}).get("data") or {}
            container = data.get("purchasedTitlesRetrieve") or {}
            games = container.get("games") or []
            return [
                {"titleId": title["titleId"], "name": title["name"], "source": "purchased"}
                for title in games
                if title.get("titleId") and title.get("name")
            ]
        except (KeyError, TypeError, AttributeError) as exc:
            raise UnknownBackendResponse(str(exc)) from exc

    async def get_purchased_games(self) -> List[Dict[str, str]]:
        if self._purchased_memo is not None:
            fetched_at, games = self._purchased_memo
            if time.monotonic() - fetched_at < LIBRARY_SOURCE_MEMO_TTL:
                return games

        try:
            all_games: List[Dict[str, str]] = []
            start = 0
            page = DEFAULT_PAGE_SIZE
            while True:
                response = await self._http_client.graphql_get(
                    purchased_games_url(start=start, size=page)
                )
                batch = self._parse_purchased(response)
                all_games.extend(batch)
                logger.info("Fetched %d purchased games (start=%d)", len(batch), start)
                if len(batch) < page:
                    break
                start += page
        except Exception:
            cached = self._cache_load(CACHE_PURCHASED, None)
            if cached is None:
                raise
            logger.warning(
                "Purchased games fetch failed; using %d cached entries",
                len(cached),
                exc_info=True,
            )
            return cached
        self._cache_store(CACHE_PURCHASED, all_games)
        self._purchased_memo = (time.monotonic(), all_games)
        return all_games

    async def get_played_games_graphql(self) -> List[Dict[str, str]]:
        response = await self._http_client.graphql_get(
            played_games_url(limit=DEFAULT_PAGE_SIZE)
        )
        try:
            data = (response or {}).get("data") or {}
            container = data.get("gameLibraryTitlesRetrieve") or {}
            games = container.get("games") or []
            return [
                {"titleId": title["titleId"], "name": title["name"], "source": "played"}
                for title in games
                if title.get("titleId") and title.get("name")
            ]
        except (KeyError, TypeError, AttributeError) as exc:
            raise UnknownBackendResponse(str(exc)) from exc

    @staticmethod
    def _slim_played_title(title: Dict[str, Any]) -> Dict[str, Any]:
        """Keep only the fields the plugin uses so the persistent cache stays small."""
        concept = title.get("concept") or {}
        return {
            "titleId": title.get("titleId"),
            "name": title.get("name"),
            "localizedName": title.get("localizedName"),
            "category": title.get("category"),
            "playDuration": title.get("playDuration"),
            "lastPlayedDateTime": title.get("lastPlayedDateTime"),
            "concept": {
                "id": concept.get("id"),
                "name": concept.get("name"),
                "titleIds": concept.get("titleIds") or [],
            },
        }

    async def get_played_games(self, refresh: bool = False) -> List[Dict[str, Any]]:
        if not refresh and self._played_games_cache is not None:
            return self._played_games_cache

        try:
            all_titles: List[Dict[str, Any]] = []
            offset = 0
            page = PLAYED_GAMES_PAGE_SIZE
            skipped_unknown = 0
            while True:
                response = await self._http_client.api_get(
                    rest_played_games_url(limit=page, offset=offset)
                )
                titles = response.get("titles") or []
                for title in titles:
                    if title.get("category") == "unknown":
                        if not pick_display_name(
                            title.get("name"),
                            title.get("localizedName"),
                            (title.get("concept") or {}).get("name"),
                        ):
                            skipped_unknown += 1
                            continue
                    all_titles.append(self._slim_played_title(title))
                logger.info(
                    "Fetched %d played games (offset=%d, skipped_unknown=%d)",
                    len(titles),
                    offset,
                    skipped_unknown,
                )
                if len(titles) < page:
                    break
                offset += page
        except Exception:
            if refresh and self._played_games_cache is not None:
                logger.warning("Played games refresh failed; keeping snapshot", exc_info=True)
                return self._played_games_cache
            cached = self._cache_load(CACHE_PLAYED, None)
            if cached is None:
                raise
            logger.warning(
                "Played games fetch failed; using %d cached entries",
                len(cached),
                exc_info=True,
            )
            self._played_games_cache = cached
            return cached

        self._cache_store(CACHE_PLAYED, all_titles)
        self._played_games_cache = all_titles
        return all_titles

    async def get_trophy_library_games(self, refresh: bool = False) -> List[Dict[str, str]]:
        if not refresh and self._trophy_titles_memo is not None:
            fetched_at, titles = self._trophy_titles_memo
            if time.monotonic() - fetched_at < LIBRARY_SOURCE_MEMO_TTL:
                return titles

        try:
            all_titles: List[Dict[str, str]] = []
            offset = 0
            page = TROPHY_TITLES_PAGE_SIZE
            index: Dict[str, Dict[str, str]] = {}
            while True:
                response = await self._http_client.api_get(
                    trophy_titles_url(limit=page, offset=offset)
                )
                batch = response.get("trophyTitles") or []
                for title in batch:
                    np_id = title.get("npCommunicationId")
                    if not np_id:
                        continue
                    platform = title.get("trophyTitlePlatform") or ""
                    np_service = title.get("npServiceName") or (
                        "trophy2" if "PS5" in platform else "trophy"
                    )
                    index[np_id] = {
                        "npCommunicationId": np_id,
                        "npServiceName": np_service,
                        "name": title.get("trophyTitleName") or "",
                        "platform": platform,
                        "lastUpdated": title.get("lastUpdatedDateTime") or "",
                    }
                    if title.get("hiddenFlag"):
                        continue
                    name = title.get("trophyTitleName")
                    if not name:
                        continue
                    all_titles.append(
                        {
                            "titleId": np_id,
                            "name": name,
                            "source": "trophy",
                        }
                    )
                logger.info("Fetched %d trophy titles (offset=%d)", len(batch), offset)
                if len(batch) < page:
                    break
                offset += page
        except Exception:
            cached = self._cache_load(CACHE_TROPHY_TITLES, None)
            if cached is None:
                raise
            logger.warning(
                "Trophy titles fetch failed; using %d cached entries",
                len(cached.get("titles") or []),
                exc_info=True,
            )
            self._trophy_title_index = cached.get("index") or {}
            return cached.get("titles") or []

        self._cache_store(CACHE_TROPHY_TITLES, {"titles": all_titles, "index": index})
        self._trophy_title_index = index
        self._trophy_titles_memo = (time.monotonic(), all_titles)
        return all_titles

    async def get_all_library_titles(self) -> List[Dict[str, str]]:
        try:
            library = await self._build_library_titles()
        except Exception:
            # Last line of defense: serve the previous complete library so a
            # transient Sony failure never shrinks what Galaxy sees.
            cached = self._cache_load(CACHE_LIBRARY, None)
            if cached is None:
                raise
            logger.warning(
                "Library build failed; using %d cached titles",
                len(cached),
                exc_info=True,
            )
            self._owned_ids = {title["titleId"] for title in cached}
            return cached
        self._cache_store(CACHE_LIBRARY, library)
        self._owned_ids = {title["titleId"] for title in library}
        return library

    async def _build_library_titles(self) -> List[Dict[str, str]]:
        purchased_games = await self.get_purchased_games()
        try:
            played_games = await self.get_played_games()
        except Exception:
            logger.warning("REST played games unavailable, trying GraphQL fallback", exc_info=True)
            try:
                played_games = await self.get_played_games_graphql()
            except Exception:
                logger.warning("Could not fetch played games", exc_info=True)
                played_games = []

        try:
            trophy_games = await self.get_trophy_library_games()
        except Exception:
            logger.warning("Could not fetch trophy titles for library expansion", exc_info=True)
            trophy_games = []

        purchased_ids = {game["titleId"] for game in purchased_games}
        played_entries = [
            {
                **title,
                "source": "played",
                "conceptId": (title.get("concept") or {}).get("id"),
                "name": pick_display_name(
                    title.get("localizedName"),
                    title.get("name"),
                    (title.get("concept") or {}).get("name"),
                ),
            }
            for title in played_games
            if isinstance(title, dict)
        ]
        self._concept_siblings = build_concept_siblings(played_games)

        # Trophy sets belonging to an owned store SKU must not create a
        # second library entry: collections like Spyro Reignited Trilogy
        # carry several differently-named trophy sets under one store title,
        # so exclusion has to work by id. Resolve mappings for all owned
        # store titles up front (batched, cached permanently).
        store_ids = sorted(
            {
                entry["titleId"]
                for entry in purchased_games + played_entries
                if entry.get("titleId", "").startswith(STORE_TITLE_PREFIXES)
            }
        )
        await self._ensure_store_trophy_mappings(store_ids)

        mapped_np_comm_ids = set()
        for mapping in self._store_trophy_map.values():
            trophy_sets = (
                mapping if isinstance(mapping, list) else mapping.get("sets") or []
            )
            for trophy_set in trophy_sets:
                np_comm_id = trophy_set.get("npCommunicationId")
                if np_comm_id:
                    mapped_np_comm_ids.add(np_comm_id)

        known_names = {
            normalize_title(entry.get("name"))
            for entry in purchased_games + played_entries
        }

        trophy_only = []
        for game in trophy_games:
            if game["titleId"] in purchased_ids:
                continue
            if game["titleId"].startswith(STORE_TITLE_PREFIXES):
                continue
            if game["titleId"] in mapped_np_comm_ids:
                continue
            meta = self._trophy_title_index.get(game["titleId"], {})
            platform = meta.get("platform") or ""
            if any(tag in platform for tag in ("PS4", "PS5", "PSPC")):
                # Modern games usually arrive via the purchased/played lists,
                # but disc games that were sold and expired PS Plus titles
                # exist only here (issue #48 follow-up: missing God of War).
                # Keep them unless a purchased/played entry already carries
                # the same name.
                if normalize_title(game.get("name")) in known_names:
                    continue
            trophy_only.append(game)

        # Emit exactly the title ids the account actually owns or played —
        # never invent siblings (issue #48: 17x duplicates) and never merge
        # by Sony concept (concepts group soundtracks/demos with the game,
        # collapsing real games like KNACK 2 into their soundtrack SKU).
        # GOG's backend stacks releases of the same game on its own.
        library = merge_library_entries(purchased_games + played_entries + trophy_only)
        logger.info(
            "Total library titles: %d (purchased=%d, played=%d, trophy-only=%d)",
            len(library),
            len(purchased_games),
            len(played_entries),
            len(trophy_only),
        )
        return library

    async def build_game_times_context(self, game_ids: List[str]) -> Dict[str, GameTime]:
        try:
            played_games = await self.get_played_games()
        except Exception:
            logger.warning("Could not fetch played games for game time import", exc_info=True)
            return {}

        wanted = set(game_ids)
        context: Dict[str, GameTime] = {}
        for title in played_games:
            title_id = title.get("titleId")
            if title_id not in wanted:
                continue
            context[title_id] = GameTime(
                game_id=title_id,
                time_played=parse_play_duration(title.get("playDuration")),
                last_played_time=parse_iso_datetime(title.get("lastPlayedDateTime")),
            )
        if not self._concept_siblings:
            self._concept_siblings = build_concept_siblings(played_games)
        alias_context_by_siblings(
            context,
            game_ids,
            self._concept_siblings,
            has_data=lambda item: item.time_played is not None
            or item.last_played_time is not None,
        )
        with_time = sum(
            1 for item in context.values() if item.time_played is not None
        )
        logger.info(
            "Prepared game time data for %d/%d games (%d with play time)",
            len(context),
            len(game_ids),
            with_time,
        )
        return context

    @staticmethod
    def _is_store_title_id(game_id: str) -> bool:
        return game_id.startswith(STORE_TITLE_PREFIXES)

    async def detect_game_time_updates(self) -> List[GameTime]:
        """Refresh the played list and return GameTime for changed titles."""
        previous = self._played_games_cache
        titles = await self.get_played_games(refresh=True)
        if previous is None:
            return []
        snapshot = {
            title.get("titleId"): (
                title.get("playDuration"),
                title.get("lastPlayedDateTime"),
            )
            for title in previous
        }
        updates = []
        for title in titles:
            title_id = title.get("titleId")
            current = (title.get("playDuration"), title.get("lastPlayedDateTime"))
            if title_id and snapshot.get(title_id) != current:
                updates.append(
                    GameTime(
                        game_id=title_id,
                        time_played=parse_play_duration(current[0]),
                        last_played_time=parse_iso_datetime(current[1]),
                    )
                )
        return updates

    def exported_ids_for_np_comm(self, np_comm_id: str) -> List[str]:
        """Owned store titles (or the trophy-only id) a trophy set belongs to."""
        ids = []
        for store_id, mapping in (self._store_trophy_map or {}).items():
            trophy_sets = (
                mapping if isinstance(mapping, list) else mapping.get("sets") or []
            )
            if any(
                trophy_set.get("npCommunicationId") == np_comm_id
                for trophy_set in trophy_sets
            ):
                ids.append(store_id)
        if not ids and np_comm_id in self._trophy_title_index:
            ids.append(np_comm_id)
        return ids

    async def detect_trophy_updates(self) -> List[Tuple[str, Achievement]]:
        """Refresh trophy titles and return newly earned achievements."""
        previous_index = dict(self._trophy_title_index) if self._trophy_title_index else None
        await self.get_trophy_library_games(refresh=True)
        if previous_index is None:
            return []

        cache = self._trophy_cache_entries()
        updates: List[Tuple[str, Achievement]] = []
        for np_comm_id, meta in self._trophy_title_index.items():
            before = (previous_index.get(np_comm_id) or {}).get("lastUpdated")
            if before is None or meta.get("lastUpdated") == before:
                continue
            known_ids = {
                item[1] for item in (cache.get(np_comm_id) or {}).get("a") or []
            }
            try:
                achievements = await self._load_np_comm_achievements(
                    np_comm_id, meta.get("npServiceName") or "trophy"
                )
            except Exception:
                logger.warning(
                    "Could not refresh trophies for %s", np_comm_id, exc_info=True
                )
                continue
            fresh = [
                achievement
                for achievement in achievements
                if achievement.achievement_id not in known_ids
            ]
            if not fresh:
                continue
            for game_id in self.exported_ids_for_np_comm(np_comm_id):
                for achievement in fresh:
                    updates.append((game_id, achievement))
        return updates

    def _trophy_cache_entries(self) -> Dict[str, dict]:
        if self._trophy_cache is None:
            self._trophy_cache = self._cache_load(CACHE_TROPHIES, {})
        return self._trophy_cache

    async def _load_np_comm_achievements(
        self, np_comm_id: str, np_service_name: str
    ) -> List[Achievement]:
        # Skip both API calls when Sony reports no trophy activity since the
        # cached copy was taken (lastUpdatedDateTime is bumped on any unlock).
        meta = self._trophy_title_index.get(np_comm_id) or {}
        last_updated = meta.get("lastUpdated") or ""
        cache = self._trophy_cache_entries()
        entry = cache.get(np_comm_id)
        if entry and last_updated and entry.get("u") == last_updated:
            return [
                Achievement(
                    unlock_time=item[0],
                    achievement_id=item[1],
                    achievement_name=item[2],
                )
                for item in entry.get("a") or []
            ]

        earned_response = await self._http_client.api_get(
            user_trophies_earned_url(
                np_communication_id=np_comm_id,
                np_service_name=np_service_name,
            )
        )
        title_response = await self._http_client.api_get(
            title_trophies_url(
                np_communication_id=np_comm_id,
                np_service_name=np_service_name,
            )
        )
        achievements = merge_earned_with_definitions(
            earned_response, title_response, np_comm_id
        )
        if last_updated:
            cache[np_comm_id] = {
                "u": last_updated,
                "a": [
                    [item.unlock_time, item.achievement_id, item.achievement_name]
                    for item in achievements
                ],
            }
            self._cache_store(CACHE_TROPHIES, cache)
        return achievements

    async def _ensure_store_trophy_mappings(self, store_ids: List[str]) -> None:
        """Batch-resolve store-title -> trophy-set mappings for owned games."""
        if self._store_trophy_map is None:
            self._store_trophy_map = self._cache_load(CACHE_STORE_TROPHY_MAP, {})
        now = time.time()
        unknown = []
        for store_id in store_ids:
            entry = self._store_trophy_map.get(store_id)
            if isinstance(entry, list):
                continue
            if isinstance(entry, dict) and (
                entry.get("sets") or entry.get("neg", 0) > now
            ):
                continue
            unknown.append(store_id)
        if not unknown:
            return

        logger.info(
            "Resolving trophy-set mappings for %d store titles", len(unknown)
        )
        try:
            for start in range(0, len(unknown), STORE_TROPHY_BATCH_SIZE):
                batch = unknown[start : start + STORE_TROPHY_BATCH_SIZE]
                response = await self._http_client.api_get(
                    user_trophies_for_titles_url(np_title_ids=",".join(batch)),
                    not_found_ok=True,
                )
                mappings = (
                    extract_store_title_mappings(response) if response else {}
                )
                for store_id in batch:
                    trophy_sets = mappings.get(store_id) or []
                    if trophy_sets:
                        self._store_trophy_map[store_id] = {"sets": trophy_sets}
                    else:
                        self._store_trophy_map[store_id] = {
                            "neg": now + STORE_TROPHY_NEGATIVE_TTL
                        }
        except Exception:
            # Partial mappings are still useful; the name guard covers the rest.
            logger.warning(
                "Trophy-set mapping resolution interrupted; continuing with "
                "%d mappings",
                len(self._store_trophy_map),
                exc_info=True,
            )
        self._cache_store(CACHE_STORE_TROPHY_MAP, self._store_trophy_map)

    async def _resolve_store_trophy_sets(self, store_id: str) -> List[dict]:
        # A store title's trophy-set mapping never changes once it exists, so
        # positive hits are cached forever; games with no trophy activity are
        # negative-cached with an expiry so they don't cost one request per
        # game on every sync.
        if self._store_trophy_map is None:
            self._store_trophy_map = self._cache_load(CACHE_STORE_TROPHY_MAP, {})
        entry = self._store_trophy_map.get(store_id)
        if isinstance(entry, list):  # legacy positive entry
            return entry
        if isinstance(entry, dict):
            if entry.get("sets"):
                return entry["sets"]
            if entry.get("neg", 0) > time.time():
                return []

        response = await self._http_client.api_get(
            user_trophies_for_titles_url(np_title_ids=store_id),
            not_found_ok=True,
        )
        trophy_sets = (
            extract_store_title_mappings(response).get(store_id, [])
            if response
            else []
        )
        if trophy_sets:
            self._store_trophy_map[store_id] = {"sets": trophy_sets}
        else:
            self._store_trophy_map[store_id] = {
                "neg": time.time() + STORE_TROPHY_NEGATIVE_TTL
            }
        self._cache_store(CACHE_STORE_TROPHY_MAP, self._store_trophy_map)
        return trophy_sets

    async def _fetch_achievements_for_title(self, game_id: str) -> List[Achievement]:
        if self._is_store_title_id(game_id):
            trophy_sets = await self._resolve_store_trophy_sets(game_id)
            if not trophy_sets:
                return []
            earned: List[Achievement] = []
            for trophy_set in trophy_sets:
                np_comm_id = trophy_set.get("npCommunicationId")
                if not np_comm_id:
                    continue
                try:
                    earned.extend(
                        await self._load_np_comm_achievements(
                            np_comm_id,
                            trophy_set.get("npServiceName") or "trophy",
                        )
                    )
                except TRANSIENT_TROPHY_ERRORS:
                    raise
                except Exception:
                    logger.debug(
                        "Could not fetch trophies for %s (%s)",
                        game_id,
                        np_comm_id,
                        exc_info=True,
                    )
            return earned

        meta = self._trophy_title_index.get(game_id)
        if not meta:
            return []
        np_service = meta.get("npServiceName") or "trophy"
        try:
            return await self._load_np_comm_achievements(game_id, np_service)
        except TRANSIENT_TROPHY_ERRORS:
            raise
        except Exception:
            logger.debug("Could not fetch trophies for %s", game_id, exc_info=True)
            return []

    async def prepare_achievements_context(
        self, game_ids: List[str]
    ) -> AchievementsContext:
        if not self._trophy_title_index:
            try:
                await self.get_trophy_library_games()
            except Exception:
                logger.warning("Could not load trophy title index", exc_info=True)

        if not self._concept_siblings:
            try:
                played_games = await self.get_played_games()
                self._concept_siblings = build_concept_siblings(played_games)
            except Exception:
                logger.debug("Could not build concept sibling map", exc_info=True)

        logger.info(
            "Prepared achievements context for %d games (index=%d titles, siblings=%d)",
            len(game_ids),
            len(self._trophy_title_index),
            len(self._concept_siblings),
        )
        return AchievementsContext(
            concept_siblings=dict(self._concept_siblings),
            trophy_title_index=dict(self._trophy_title_index),
        )

    def _cache_achievements_for_siblings(
        self,
        context: AchievementsContext,
        game_id: str,
        achievements: List[Achievement],
    ) -> None:
        context.cache[game_id] = achievements
        if not achievements:
            return
        for sibling_id in context.concept_siblings.get(game_id, []):
            context.cache[sibling_id] = achievements

    async def fetch_unlocked_achievements(
        self, game_id: str, context: AchievementsContext
    ) -> List[Achievement]:
        if game_id in context.cache:
            return context.cache[game_id]

        if not context.trophy_title_index and self._trophy_title_index:
            context.trophy_title_index = dict(self._trophy_title_index)

        aliased_from = None
        # Galaxy requests every game's trophies at once; bound the fan-out so
        # requests don't starve the connection pool and time out.
        async with self._trophy_semaphore:
            if game_id not in context.cache:
                achievements = await self._fetch_achievements_for_title(game_id)
                self._cache_achievements_for_siblings(context, game_id, achievements)

                if not achievements:
                    for sibling_id in context.concept_siblings.get(game_id, []):
                        # Sony concepts list regional SKUs the account never
                        # owned; probing those is a guaranteed 404 and reads
                        # as requests for games Galaxy was never sent.
                        if self._owned_ids and sibling_id not in self._owned_ids:
                            continue
                        if sibling_id not in context.cache:
                            sibling_achievements = (
                                await self._fetch_achievements_for_title(sibling_id)
                            )
                            self._cache_achievements_for_siblings(
                                context, sibling_id, sibling_achievements
                            )
                        sibling_achievements = context.cache.get(sibling_id) or []
                        if sibling_achievements:
                            aliased_from = sibling_id
                            self._cache_achievements_for_siblings(
                                context, game_id, sibling_achievements
                            )
                            break

        result = context.cache.get(game_id, [])
        if result:
            context.games_with_trophies += 1
            context.total_unlocked += len(result)
            if aliased_from:
                logger.info(
                    "Trophies for %s: %d unlocked (from sibling %s)",
                    game_id,
                    len(result),
                    aliased_from,
                )
            else:
                logger.info(
                    "Trophies for %s: %d unlocked", game_id, len(result)
                )
        else:
            context.games_empty += 1
            reason = "no PSN trophy set"
            if self._is_store_title_id(game_id):
                reason = "no store→trophy mapping"
            elif game_id not in self._trophy_title_index:
                reason = "not in trophy index"
            logger.info(
                "Trophies for %s: none (%s, siblings=%s)",
                game_id,
                reason,
                context.concept_siblings.get(game_id, []),
            )
        return result

    async def _load_friend_profile(self, account_id: str) -> Optional[UserInfo]:
        try:
            profile = await self._http_client.api_get(rest_profile_url(account_id))
        except Exception:
            logger.debug("Could not load profile for friend %s", account_id, exc_info=True)
            return None

        avatar_url = None
        for avatar in profile.get("avatars") or []:
            if avatar.get("size") == "l":
                avatar_url = avatar.get("url")
                break
        if avatar_url is None and profile.get("avatars"):
            avatar_url = profile["avatars"][0].get("url")

        online_id = profile.get("onlineId") or str(account_id)
        return UserInfo(
            user_id=str(account_id),
            user_name=online_id,
            avatar_url=avatar_url,
            profile_url=f"https://profile.playstation.com/{online_id}",
        )

    async def get_friends(self) -> List[UserInfo]:
        response = await self._http_client.api_get(
            friends_url(limit=FRIENDS_PAGE_SIZE, offset=0)
        )
        account_ids = response.get("friends") or []
        friends: List[UserInfo] = []
        for index in range(0, len(account_ids), FRIENDS_PROFILE_BATCH):
            batch = account_ids[index : index + FRIENDS_PROFILE_BATCH]
            results = await asyncio.gather(
                *(self._load_friend_profile(account_id) for account_id in batch)
            )
            friends.extend(friend for friend in results if friend is not None)
        logger.info("Fetched %d friends", len(friends))
        return friends
