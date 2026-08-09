import pytest

from psn.client import PSNClient
from psn.duration import parse_play_duration
from psn.library_utils import merge_library_entries, pick_display_name
from psn.rest_urls import user_trophies_for_titles_url

FAR_FUTURE = 4_000_000_000_000.0


def preset_no_mappings(client, store_ids, extra=None):
    """Mark store ids as having no trophy sets so no resolution requests fire."""
    mapping = {store_id: {"neg": FAR_FUTURE} for store_id in store_ids}
    mapping.update(extra or {})
    client._store_trophy_map = mapping
    client._persistent_cache = None


class StubPSNClient(PSNClient):
    def __init__(self):
        pass

    async def get_purchased_games(self):
        return [
            {"titleId": "CUSA12345_00", "name": "Test Game One", "source": "purchased"},
            {"titleId": "CUSA67890_00", "name": "Test Game Two", "source": "purchased"},
        ]

    async def get_played_games(self):
        return [
            {
                "titleId": "CUSA67890_00",
                "name": "Worse Name",
                "localizedName": "Test Game Two (Played)",
                "source": "played",
            },
            {
                "titleId": "CUSA11111_00",
                "name": "Played Only Game",
                "localizedName": "Played Only Game",
                "source": "played",
            },
        ]

    async def get_trophy_library_games(self):
        return [
            {
                "titleId": "NPWR01234_00",
                "name": "PS3 Classic",
                "source": "trophy",
            }
        ]


@pytest.mark.asyncio
async def test_get_all_library_titles_merges_and_dedupes():
    client = StubPSNClient()
    preset_no_mappings(client, ["CUSA12345_00", "CUSA67890_00", "CUSA11111_00"])
    client._trophy_title_index = {
        "NPWR01234_00": {
            "npCommunicationId": "NPWR01234_00",
            "npServiceName": "trophy",
            "name": "PS3 Classic",
            "platform": "PS3",
        }
    }
    titles = await client.get_all_library_titles()

    assert len(titles) == 4
    title_ids = {title["titleId"] for title in titles}
    assert title_ids == {
        "CUSA12345_00",
        "CUSA67890_00",
        "CUSA11111_00",
        "NPWR01234_00",
    }
    merged = {title["titleId"]: title["name"] for title in titles}
    assert merged["CUSA67890_00"] == "Test Game Two (Played)"


class MultiRegionStubClient(PSNClient):
    """One game owned as several regional SKUs plus its PS5 version."""

    def __init__(self):
        pass

    async def get_purchased_games(self):
        return [
            {"titleId": f"CUSA{10000 + i:05d}_00", "name": "Final Fantasy XV", "source": "purchased"}
            for i in range(3)
        ]

    async def get_played_games(self):
        concept_ids = [f"CUSA{10000 + i:05d}_00" for i in range(3)] + ["PPSA55555_00"]
        return [
            {
                "titleId": "PPSA55555_00",
                "name": "Final Fantasy XV",
                "localizedName": "Final Fantasy XV",
                "concept": {"id": 777, "name": "Final Fantasy XV", "titleIds": concept_ids},
                "source": "played",
            }
        ]

    async def get_trophy_library_games(self):
        return []


@pytest.mark.asyncio
async def test_get_all_library_titles_emits_exactly_owned_ids():
    # No invented sibling SKUs (issue #48: 17x duplicates) and no concept
    # merging (Sony concepts group soundtracks with the game): every owned
    # id is emitted as-is; GOG's backend stacks same-game releases itself.
    client = MultiRegionStubClient()
    preset_no_mappings(
        client,
        [f"CUSA{10000 + i:05d}_00" for i in range(3)] + ["PPSA55555_00"],
    )
    client._trophy_title_index = {}
    titles = await client.get_all_library_titles()

    assert {title["titleId"] for title in titles} == {
        "CUSA10000_00",
        "CUSA10001_00",
        "CUSA10002_00",
        "PPSA55555_00",
    }
    # Siblings are still tracked for play-time/trophy aliasing.
    assert "CUSA10000_00" in client._concept_siblings


class KnackStubClient(PSNClient):
    """toptaran's case: game + sequel + soundtrack share one Sony concept."""

    def __init__(self):
        pass

    async def get_purchased_games(self):
        return [
            {"titleId": "CUSA00006_00", "name": "KNACK", "source": "purchased"},
            {"titleId": "CUSA07670_00", "name": "KNACK2", "source": "purchased"},
            {
                "titleId": "CUSA09758_00",
                # Localized (Russian) soundtrack name: keyword filters can't
                # catch this, which is why concept merging had to go.
                "name": "Саундтрек игры KNACK™ 2",
                "source": "purchased",
            },
        ]

    async def get_played_games(self):
        return [
            {
                "titleId": "CUSA07670_00",
                "name": "KNACK2",
                "localizedName": "KNACK2",
                "concept": {
                    "id": 888,
                    "name": "KNACK 2",
                    "titleIds": ["CUSA07670_00", "CUSA09758_00"],
                },
                "source": "played",
            }
        ]

    async def get_trophy_library_games(self):
        return []


@pytest.mark.asyncio
async def test_soundtrack_sharing_concept_never_swallows_the_game():
    client = KnackStubClient()
    preset_no_mappings(
        client, ["CUSA00006_00", "CUSA07670_00", "CUSA09758_00"]
    )
    client._trophy_title_index = {}
    titles = await client.get_all_library_titles()
    by_id = {title["titleId"]: title["name"] for title in titles}

    assert set(by_id) == {"CUSA00006_00", "CUSA07670_00", "CUSA09758_00"}
    assert by_id["CUSA07670_00"] in ("KNACK2", "KNACK 2")
    assert "Саундтрек" not in by_id["CUSA07670_00"]


class FakeHttp:
    def __init__(self, responses):
        self._responses = responses
        self.calls = []

    async def api_get(self, url, **kwargs):
        self.calls.append(url)
        return self._responses[url]


class SpyroStubClient(PSNClient):
    """One purchased collection whose three trophy sets have their own names."""

    def __init__(self):
        pass

    async def get_purchased_games(self):
        return [
            {
                "titleId": "CUSA12085_00",
                "name": "Spyro Reignited Trilogy",
                "source": "purchased",
            }
        ]

    async def get_played_games(self):
        return []

    async def get_trophy_library_games(self):
        return [
            {"titleId": "NPWR15579_00", "name": "Spyro the Dragon", "source": "trophy"},
            {"titleId": "NPWR15891_00", "name": "Spyro 2: Ripto's Rage!", "source": "trophy"},
            {"titleId": "NPWR15892_00", "name": "Spyro 3: Year of the Dragon", "source": "trophy"},
        ]


@pytest.mark.asyncio
async def test_collection_trophy_sets_never_become_library_entries():
    # rc3 tester regression: on a fresh connect (empty mapping cache) the
    # Spyro trilogy's three trophy sets appeared as three extra games.
    mapping_url = user_trophies_for_titles_url(np_title_ids="CUSA12085_00")
    client = SpyroStubClient()
    client._http_client = FakeHttp(
        {
            mapping_url: {
                "titles": [
                    {
                        "npTitleId": "CUSA12085_00",
                        "trophyTitles": [
                            {"npCommunicationId": "NPWR15579_00", "npServiceName": "trophy"},
                            {"npCommunicationId": "NPWR15891_00", "npServiceName": "trophy"},
                            {"npCommunicationId": "NPWR15892_00", "npServiceName": "trophy"},
                        ],
                    }
                ]
            }
        }
    )
    client._store_trophy_map = None  # fresh connect: nothing cached
    client._persistent_cache = None
    client._trophy_title_index = {
        "NPWR15579_00": {"platform": "PS4"},
        "NPWR15891_00": {"platform": "PS4"},
        "NPWR15892_00": {"platform": "PS4"},
    }

    titles = await client.get_all_library_titles()

    assert [title["titleId"] for title in titles] == ["CUSA12085_00"]
    assert client._http_client.calls == [mapping_url]


def test_pick_display_name_prefers_localized():
    assert pick_display_name("Short", "Longer Localized Name") == "Longer Localized Name"


def test_pick_display_name_avoids_soundtrack_names():
    assert (
        pick_display_name("KNACK 2 + Original Soundtrack Bundle", "KNACK 2")
        == "KNACK 2"
    )


class TrophyOnlyStubClient(PSNClient):
    """PS4 game visible only via trophies (sold disc / expired PS Plus)."""

    def __init__(self):
        pass

    async def get_purchased_games(self):
        return [
            {"titleId": "CUSA99999_00", "name": "God of War Ragnarok", "source": "purchased"}
        ]

    async def get_played_games(self):
        return []

    async def get_trophy_library_games(self):
        return [
            {"titleId": "NPWR12345_00", "name": "God of War", "source": "trophy"},
            {"titleId": "NPWR23456_00", "name": "God of War Ragnarok", "source": "trophy"},
            {"titleId": "NPWR34567_00", "name": "Mapped Game", "source": "trophy"},
        ]


@pytest.mark.asyncio
async def test_ps4_trophy_only_games_kept_unless_already_represented():
    client = TrophyOnlyStubClient()
    client._trophy_title_index = {
        "NPWR12345_00": {"platform": "PS4"},
        "NPWR23456_00": {"platform": "PS4,PS5"},
        "NPWR34567_00": {"platform": "PS5"},
    }
    preset_no_mappings(
        client,
        ["CUSA99999_00"],
        extra={"CUSA88888_00": {"sets": [{"npCommunicationId": "NPWR34567_00"}]}},
    )
    titles = await client.get_all_library_titles()
    title_ids = {title["titleId"] for title in titles}

    # Trophy-only God of War (2018) is a real game the store lists miss.
    assert "NPWR12345_00" in title_ids
    # Ragnarok's trophy set duplicates the purchased entry -> excluded.
    assert "NPWR23456_00" not in title_ids
    # Trophy sets mapped to a store SKU never create a second entry.
    assert "NPWR34567_00" not in title_ids
    assert "CUSA99999_00" in title_ids


def test_merge_library_entries_skips_unknown_without_name():
    merged = merge_library_entries(
        [
            {"titleId": "CUSA99999_00", "category": "unknown"},
            {"titleId": "CUSA88888_00", "name": "Real Game"},
        ]
    )
    assert len(merged) == 1
    assert merged[0]["titleId"] == "CUSA88888_00"


@pytest.mark.parametrize(
    "duration,minutes",
    [
        ("PT1H30M", 90),
        ("PT228H56M33S", 228 * 60 + 56 + 1),
        ("P1DT2H", 26 * 60),
        (None, None),
        ("invalid", None),
    ],
)
def test_parse_play_duration(duration, minutes):
    assert parse_play_duration(duration) == minutes
