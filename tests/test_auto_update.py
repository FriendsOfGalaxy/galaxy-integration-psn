import pytest

from psn.client import PSNClient
from psn.constants import PLAYED_GAMES_PAGE_SIZE, TROPHY_TITLES_PAGE_SIZE
from psn.rest_urls import (
    played_games_url as rest_played_games_url,
    title_trophies_url,
    trophy_titles_url,
    user_trophies_earned_url,
)

PLAYED_URL = rest_played_games_url(limit=PLAYED_GAMES_PAGE_SIZE, offset=0)
TROPHY_TITLES_URL = trophy_titles_url(limit=TROPHY_TITLES_PAGE_SIZE, offset=0)
NP_COMM_ID = "NPWR11111_00"


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


def played_title(title_id, name, duration, last_played):
    return {
        "titleId": title_id,
        "name": name,
        "localizedName": name,
        "category": "ps5_native_game",
        "playDuration": duration,
        "lastPlayedDateTime": last_played,
        "concept": {"id": 1, "name": name, "titleIds": []},
    }


@pytest.mark.asyncio
async def test_detect_game_time_updates_reports_only_changes():
    client = PSNClient(
        FakeHttpClient(
            {
                PLAYED_URL: {
                    "titles": [
                        played_title("PPSA00001_00", "Game A", "PT5H", "2026-08-06T12:00:00Z"),
                        played_title("PPSA00002_00", "Game B", "PT1H", "2026-08-01T00:00:00Z"),
                    ]
                }
            }
        )
    )
    client._played_games_cache = [
        played_title("PPSA00001_00", "Game A", "PT4H", "2026-08-05T00:00:00Z"),
        played_title("PPSA00002_00", "Game B", "PT1H", "2026-08-01T00:00:00Z"),
    ]

    updates = await client.detect_game_time_updates()

    assert len(updates) == 1
    assert updates[0].game_id == "PPSA00001_00"
    assert updates[0].time_played == 300


@pytest.mark.asyncio
async def test_detect_game_time_updates_silent_without_snapshot():
    client = PSNClient(
        FakeHttpClient(
            {
                PLAYED_URL: {
                    "titles": [
                        played_title("PPSA00001_00", "Game A", "PT5H", "2026-08-06T12:00:00Z")
                    ]
                }
            }
        )
    )

    assert await client.detect_game_time_updates() == []


@pytest.mark.asyncio
async def test_detect_trophy_updates_pushes_new_unlocks_to_store_id():
    earned_url = user_trophies_earned_url(
        np_communication_id=NP_COMM_ID, np_service_name="trophy"
    )
    title_url = title_trophies_url(NP_COMM_ID, np_service_name="trophy")
    client = PSNClient(
        FakeHttpClient(
            {
                TROPHY_TITLES_URL: {
                    "trophyTitles": [
                        {
                            "npCommunicationId": NP_COMM_ID,
                            "trophyTitleName": "Game A",
                            "trophyTitlePlatform": "PS5",
                            "npServiceName": "trophy",
                            "lastUpdatedDateTime": "2026-08-06T13:00:00Z",
                        }
                    ]
                },
                earned_url: {
                    "trophies": [
                        {"trophyId": 1, "earned": True, "earnedDateTime": "2026-08-01T00:00:00Z"},
                        {"trophyId": 2, "earned": True, "earnedDateTime": "2026-08-06T12:59:00Z"},
                    ]
                },
                title_url: {
                    "trophies": [
                        {"trophyId": 1, "trophyName": "Old Trophy"},
                        {"trophyId": 2, "trophyName": "New Trophy"},
                    ]
                },
            }
        )
    )
    client._trophy_title_index = {
        NP_COMM_ID: {
            "npServiceName": "trophy",
            "platform": "PS5",
            "lastUpdated": "2026-08-01T00:00:00Z",
        }
    }
    client._trophy_cache = {
        NP_COMM_ID: {"u": "2026-08-01T00:00:00Z", "a": [[1754006400, f"{NP_COMM_ID}_1", "Old Trophy"]]}
    }
    client._store_trophy_map = {
        "PPSA00001_00": {"sets": [{"npCommunicationId": NP_COMM_ID}]}
    }

    updates = await client.detect_trophy_updates()

    assert len(updates) == 1
    game_id, achievement = updates[0]
    assert game_id == "PPSA00001_00"
    assert achievement.achievement_id == f"{NP_COMM_ID}_2"
    assert achievement.achievement_name == "New Trophy"


@pytest.mark.asyncio
async def test_detect_trophy_updates_noop_when_nothing_changed():
    client = PSNClient(
        FakeHttpClient(
            {
                TROPHY_TITLES_URL: {
                    "trophyTitles": [
                        {
                            "npCommunicationId": NP_COMM_ID,
                            "trophyTitleName": "Game A",
                            "trophyTitlePlatform": "PS5",
                            "npServiceName": "trophy",
                            "lastUpdatedDateTime": "2026-08-01T00:00:00Z",
                        }
                    ]
                }
            }
        )
    )
    client._trophy_title_index = {
        NP_COMM_ID: {
            "npServiceName": "trophy",
            "platform": "PS5",
            "lastUpdated": "2026-08-01T00:00:00Z",
        }
    }

    assert await client.detect_trophy_updates() == []
    # Only the trophy-titles list was fetched; no per-game requests.
    assert client._http_client.calls == [TROPHY_TITLES_URL]


@pytest.mark.asyncio
async def test_trophy_sibling_probe_skips_unowned_skus():
    # Tester report: trophy fetches went out for CUSA ids never sent to
    # Galaxy — Sony concepts list regional SKUs the account doesn't own.
    from psn.client import AchievementsContext
    from psn.rest_urls import user_trophies_for_titles_url

    owned_url = user_trophies_for_titles_url(np_title_ids="CUSA00001_00")
    http_client = FakeHttpClient(
        {owned_url: {"titles": [{"npTitleId": "CUSA00001_00", "trophyTitles": []}]}}
    )
    client = PSNClient(http_client)
    client._owned_ids = {"CUSA00001_00"}
    context = AchievementsContext(
        concept_siblings={
            "CUSA00001_00": ["CUSA24706_00", "CUSA99999_00"]  # unowned siblings
        }
    )

    achievements = await client.fetch_unlocked_achievements("CUSA00001_00", context)

    assert achievements == []
    # Only the owned title was queried; no requests for unowned siblings.
    assert http_client.calls == [owned_url]


def test_exported_ids_prefer_store_titles_with_npwr_fallback():
    client = PSNClient(FakeHttpClient({}))
    client._store_trophy_map = {
        "PPSA00001_00": {"sets": [{"npCommunicationId": NP_COMM_ID}]},
        "CUSA00002_00": {"neg": 4_000_000_000_000.0},
    }
    client._trophy_title_index = {NP_COMM_ID: {}, "NPWR22222_00": {}}

    assert client.exported_ids_for_np_comm(NP_COMM_ID) == ["PPSA00001_00"]
    assert client.exported_ids_for_np_comm("NPWR22222_00") == ["NPWR22222_00"]
    assert client.exported_ids_for_np_comm("NPWR99999_00") == []
