import json
import time

import pytest

from psn.client import (
    CACHE_LIBRARY,
    CACHE_PLAYED,
    CACHE_TROPHY_TITLES,
    PSNClient,
)
from psn.graphql import purchased_games_url
from psn.rest_urls import (
    played_games_url as rest_played_games_url,
    title_trophies_url,
    trophy_titles_url,
    user_trophies_earned_url,
    user_trophies_for_titles_url,
)
from psn.constants import (
    DEFAULT_PAGE_SIZE,
    PLAYED_GAMES_PAGE_SIZE,
    TROPHY_TITLES_PAGE_SIZE,
)

NP_COMM_ID = "NPWR11111_00"
EARNED_URL = user_trophies_earned_url(
    np_communication_id=NP_COMM_ID, np_service_name="trophy"
)
TITLE_URL = title_trophies_url(NP_COMM_ID, np_service_name="trophy")


class FakeHttpClient:
    def __init__(self, responses):
        self._responses = responses
        self.calls = []

    async def api_get(self, url, **kwargs):
        self.calls.append(url)
        result = self._responses[url]
        if isinstance(result, Exception):
            raise result
        return result

    graphql_get = api_get


def make_cached_client(http_client, cache=None):
    cache = cache if cache is not None else {}
    client = PSNClient(http_client)
    client.attach_persistent_cache(lambda: cache, lambda: None)
    return client, cache


TROPHY_RESPONSES = {
    EARNED_URL: {
        "trophies": [
            {"trophyId": 1, "earned": True, "earnedDateTime": "2026-01-01T00:00:00Z"}
        ]
    },
    TITLE_URL: {"trophies": [{"trophyId": 1, "trophyName": "First Blood"}]},
}


@pytest.mark.asyncio
async def test_trophy_fetch_skipped_when_last_updated_unchanged():
    http_client = FakeHttpClient(dict(TROPHY_RESPONSES))
    client, cache = make_cached_client(http_client)
    client._trophy_title_index = {
        NP_COMM_ID: {"npServiceName": "trophy", "lastUpdated": "2026-01-02T00:00:00Z"}
    }

    first = await client._load_np_comm_achievements(NP_COMM_ID, "trophy")
    assert len(first) == 1
    assert len(http_client.calls) == 2

    second = await client._load_np_comm_achievements(NP_COMM_ID, "trophy")
    assert len(second) == 1
    assert second[0].achievement_name == "First Blood"
    assert len(http_client.calls) == 2  # cache hit, no new requests


@pytest.mark.asyncio
async def test_trophy_cache_survives_plugin_restart():
    http_client = FakeHttpClient(dict(TROPHY_RESPONSES))
    client, cache = make_cached_client(http_client)
    index = {
        NP_COMM_ID: {"npServiceName": "trophy", "lastUpdated": "2026-01-02T00:00:00Z"}
    }
    client._trophy_title_index = index
    await client._load_np_comm_achievements(NP_COMM_ID, "trophy")

    fresh_http = FakeHttpClient({})
    restarted, _ = make_cached_client(fresh_http, cache)
    restarted._trophy_title_index = index
    achievements = await restarted._load_np_comm_achievements(NP_COMM_ID, "trophy")

    assert len(achievements) == 1
    assert fresh_http.calls == []


@pytest.mark.asyncio
async def test_trophy_refetched_when_last_updated_changes():
    http_client = FakeHttpClient(dict(TROPHY_RESPONSES))
    client, cache = make_cached_client(http_client)
    client._trophy_title_index = {
        NP_COMM_ID: {"npServiceName": "trophy", "lastUpdated": "2026-01-02T00:00:00Z"}
    }
    await client._load_np_comm_achievements(NP_COMM_ID, "trophy")

    client._trophy_title_index[NP_COMM_ID]["lastUpdated"] = "2026-02-01T00:00:00Z"
    await client._load_np_comm_achievements(NP_COMM_ID, "trophy")

    assert len(http_client.calls) == 4  # refetched both endpoints


@pytest.mark.asyncio
async def test_trophy_titles_fall_back_to_cache_on_failure():
    url = trophy_titles_url(limit=TROPHY_TITLES_PAGE_SIZE, offset=0)
    http_client = FakeHttpClient({url: RuntimeError("boom")})
    client, cache = make_cached_client(http_client)
    cache[CACHE_TROPHY_TITLES] = json.dumps(
        {
            "titles": [{"titleId": NP_COMM_ID, "name": "PS3 Classic", "source": "trophy"}],
            "index": {NP_COMM_ID: {"npServiceName": "trophy", "platform": "PS3"}},
        }
    )

    titles = await client.get_trophy_library_games()

    assert [title["titleId"] for title in titles] == [NP_COMM_ID]
    assert client._trophy_title_index[NP_COMM_ID]["platform"] == "PS3"


@pytest.mark.asyncio
async def test_played_games_fall_back_to_cache_on_failure():
    url = rest_played_games_url(limit=PLAYED_GAMES_PAGE_SIZE, offset=0)
    http_client = FakeHttpClient({url: RuntimeError("boom")})
    client, cache = make_cached_client(http_client)
    cached_titles = [
        {
            "titleId": "CUSA00001_00",
            "name": "Cached Game",
            "localizedName": "Cached Game",
            "category": "ps4_game",
            "playDuration": "PT2H",
            "lastPlayedDateTime": "2026-01-01T00:00:00Z",
            "concept": {"id": 1, "name": "Cached Game", "titleIds": []},
        }
    ]
    cache[CACHE_PLAYED] = json.dumps(cached_titles)

    titles = await client.get_played_games()

    assert titles == cached_titles


@pytest.mark.asyncio
async def test_played_games_raise_without_cache():
    url = rest_played_games_url(limit=PLAYED_GAMES_PAGE_SIZE, offset=0)
    http_client = FakeHttpClient({url: RuntimeError("boom")})
    client, _ = make_cached_client(http_client)

    with pytest.raises(RuntimeError):
        await client.get_played_games()


@pytest.mark.asyncio
async def test_full_library_served_from_cache_when_build_fails():
    # Tester report: a failed source with no per-source cache sank the whole
    # build even though the previous complete library was known.
    purchased_url = purchased_games_url(start=0, size=DEFAULT_PAGE_SIZE)
    http_client = FakeHttpClient({purchased_url: RuntimeError("expired token")})
    client, cache = make_cached_client(http_client)
    cached_library = [
        {"titleId": "CUSA00001_00", "name": "Game A", "conceptId": None},
        {"titleId": "NPWR00001_00", "name": "PS3 Game", "conceptId": None},
    ]
    cache[CACHE_LIBRARY] = json.dumps(cached_library)

    titles = await client.get_all_library_titles()

    assert titles == cached_library
    assert client._owned_ids == {"CUSA00001_00", "NPWR00001_00"}


def test_large_cache_values_compressed_and_roundtrip():
    from psn.client import CACHE_COMPRESS_PREFIX

    client, cache = make_cached_client(FakeHttpClient({}))
    big = {
        f"NPWR{i:05d}_00": {
            "u": "2026-08-06T00:00:00Z",
            "a": [[1754006400 + j, f"NPWR{i:05d}_00_{j}", f"Trophy Name {j}"] for j in range(30)],
        }
        for i in range(300)
    }
    client._cache_store("trophies_v1", big)

    stored = cache["trophies_v1"]
    assert stored.startswith(CACHE_COMPRESS_PREFIX)
    assert len(stored) < len(json.dumps(big)) / 3  # at least 3x smaller

    fresh, _ = make_cached_client(FakeHttpClient({}), cache)
    assert fresh._cache_load("trophies_v1", None) == big


def test_small_cache_values_stay_plain_and_legacy_values_load():
    client, cache = make_cached_client(FakeHttpClient({}))
    client._cache_store("small", {"a": 1})
    assert cache["small"] == '{"a":1}'

    # Values written by older builds (uncompressed, any size) still load.
    legacy = [{"titleId": f"CUSA{i:05d}_00", "name": "X" * 100} for i in range(200)]
    cache["legacy"] = json.dumps(legacy)
    assert client._cache_load("legacy", None) == legacy


@pytest.mark.asyncio
async def test_library_build_failure_raises_without_cache():
    purchased_url = purchased_games_url(start=0, size=DEFAULT_PAGE_SIZE)
    http_client = FakeHttpClient({purchased_url: RuntimeError("expired token")})
    client, _ = make_cached_client(http_client)

    with pytest.raises(RuntimeError):
        await client.get_all_library_titles()


@pytest.mark.asyncio
async def test_purchased_games_memoized_within_session():
    url = purchased_games_url(start=0, size=DEFAULT_PAGE_SIZE)
    response = {
        "data": {
            "purchasedTitlesRetrieve": {
                "games": [{"titleId": "CUSA00001_00", "name": "Game"}]
            }
        }
    }
    http_client = FakeHttpClient({url: response})
    client, _ = make_cached_client(http_client)

    first = await client.get_purchased_games()
    second = await client.get_purchased_games()

    assert first is second
    assert len(http_client.calls) == 1


@pytest.mark.asyncio
async def test_trophy_titles_memoized_within_session():
    url = trophy_titles_url(limit=TROPHY_TITLES_PAGE_SIZE, offset=0)
    response = {
        "trophyTitles": [
            {
                "npCommunicationId": NP_COMM_ID,
                "trophyTitleName": "PS3 Classic",
                "trophyTitlePlatform": "PS3",
            }
        ]
    }
    http_client = FakeHttpClient({url: response})
    client, _ = make_cached_client(http_client)

    await client.get_trophy_library_games()
    await client.get_trophy_library_games()

    assert len(http_client.calls) == 1


@pytest.mark.asyncio
async def test_store_trophy_mapping_negative_cached():
    store_id = "CUSA99999_00"
    url = user_trophies_for_titles_url(np_title_ids=store_id)
    http_client = FakeHttpClient(
        {url: {"titles": [{"npTitleId": store_id, "trophyTitles": []}]}}
    )
    client, cache = make_cached_client(http_client)

    assert await client._resolve_store_trophy_sets(store_id) == []
    assert await client._resolve_store_trophy_sets(store_id) == []
    assert len(http_client.calls) == 1  # second lookup served by negative cache

    # After the negative entry expires the mapping is re-checked.
    client._store_trophy_map[store_id] = {
        "neg": time.time() - 1
    }
    assert await client._resolve_store_trophy_sets(store_id) == []
    assert len(http_client.calls) == 2


@pytest.mark.asyncio
async def test_store_trophy_mapping_positive_cached_permanently():
    store_id = "PPSA11111_00"
    url = user_trophies_for_titles_url(np_title_ids=store_id)
    trophy_sets = [{"npCommunicationId": NP_COMM_ID, "npServiceName": "trophy2"}]
    http_client = FakeHttpClient(
        {
            url: {
                "titles": [
                    {
                        "npTitleId": store_id,
                        "trophyTitles": [
                            {
                                "npCommunicationId": NP_COMM_ID,
                                "npServiceName": "trophy2",
                                "trophyTitlePlatform": "PS5",
                            }
                        ],
                    }
                ]
            }
        }
    )
    client, cache = make_cached_client(http_client)

    assert await client._resolve_store_trophy_sets(store_id) == trophy_sets
    assert await client._resolve_store_trophy_sets(store_id) == trophy_sets
    assert len(http_client.calls) == 1

    # Survives a plugin restart via the persistent cache.
    fresh_http = FakeHttpClient({})
    restarted, _ = make_cached_client(fresh_http, cache)
    assert await restarted._resolve_store_trophy_sets(store_id) == trophy_sets
    assert fresh_http.calls == []
