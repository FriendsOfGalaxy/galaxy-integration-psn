import asyncio
from types import SimpleNamespace

import pytest
from galaxy.api.types import SubscriptionGame

from plugin import PSNPlugin


class StubPSNClient:
    def __init__(self, result):
        self._result = result

    async def get_subscription_games(self):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def make_plugin(client) -> PSNPlugin:
    plugin = object.__new__(PSNPlugin)
    plugin._psn_client = client
    plugin._owned_games_import = None
    plugin._http_client = SimpleNamespace(_access_token="token")
    return plugin


@pytest.mark.asyncio
async def test_get_subscription_games_matches_importer_contract():
    games = [SubscriptionGame(game_title="Game", game_id="CUSA00001_00")]
    plugin = make_plugin(StubPSNClient(games))

    # Mirrors galaxy.api.importer.CollectionImporter._import_element:
    # async for element in await self._get(id_, context_)
    pages = [
        page
        async for page in await plugin.get_subscription_games("PlayStation PLUS", None)
    ]

    assert pages == [games]


@pytest.mark.asyncio
async def test_get_subscription_games_yields_empty_page_on_backend_error():
    plugin = make_plugin(StubPSNClient(RuntimeError("store page changed")))

    pages = [
        page
        async for page in await plugin.get_subscription_games("PlayStation PLUS", None)
    ]

    assert pages == [[]]


class StubLibraryClient:
    def __init__(self):
        self.library_import_finished = False

    async def get_all_library_titles(self):
        await asyncio.sleep(0.02)
        self.library_import_finished = True
        return []

    async def get_psplus_status(self):
        return True

    def flush_cache(self):
        pass


@pytest.mark.asyncio
async def test_get_subscriptions_waits_for_in_flight_owned_games_import():
    client = StubLibraryClient()
    plugin = make_plugin(client)

    owned_task = asyncio.create_task(plugin.get_owned_games())
    await asyncio.sleep(0)  # let the owned games import start

    subscriptions = await plugin.get_subscriptions()

    assert client.library_import_finished, (
        "subscriptions answered before owned games import finished"
    )
    assert subscriptions[0].owned is True
    await owned_task


@pytest.mark.asyncio
async def test_get_subscriptions_answers_immediately_without_owned_import():
    plugin = make_plugin(StubLibraryClient())

    subscriptions = await plugin.get_subscriptions()

    assert subscriptions[0].subscription_name == "PlayStation PLUS"
