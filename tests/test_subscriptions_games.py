import pytest
from datetime import datetime
from galaxy.api.errors import AuthenticationRequired, UnknownBackendResponse
from psn_store import AccountUserInfo
from tests.test_data import PSPLUS_GAMES, BACKEND_STORE_FREEPSPLUS_CONTAINER, USER_ACCOUNTS_DATA, \
                PSNOW_GAMES, BACKEND_PSNOW_GAMES


@pytest.fixture()
def user_account_info():
    return AccountUserInfo(
        region='SCEA',
        language='en_US',
        country='US',
        age=17
    )


@pytest.mark.asyncio
async def test_not_authenticated_subscriptions(psn_plugin):
    with pytest.raises(AuthenticationRequired):
        await psn_plugin.get_subscriptions()


@pytest.mark.asyncio
async def test_not_authenticated_subscription_games(psn_plugin, psplus_name):
    with pytest.raises(AuthenticationRequired):
        async for games in psn_plugin.get_subscription_games(psplus_name, None):
            pass


@pytest.mark.asyncio
async def test_get_user_account_info(
    http_get,
    user_account_info,
    authenticated_psn_client,
    mocker
):
    http_get.return_value = USER_ACCOUNTS_DATA
    with mocker.patch("psn_client.date_today", return_value=datetime(year=2020, month=2, day=25)):
        assert user_account_info == await authenticated_psn_client.get_account_info()
    http_get.assert_called_once()


@pytest.mark.asyncio
async def test_get_psplus_games(
    http_get,
    user_account_info,
    authenticated_psn_client,
    mocker
):
    http_get.return_value = BACKEND_STORE_FREEPSPLUS_CONTAINER
    acc_info = user_account_info
    assert PSPLUS_GAMES == await authenticated_psn_client.get_psplus_games(acc_info)
    http_get.assert_called_once()

@pytest.mark.asyncio
async def test_get_psnow_games(
    http_get,
    user_account_info,
    authenticated_psn_client,
    mocker
):
    http_get.return_value = BACKEND_PSNOW_GAMES
    acc_info = user_account_info
    assert PSNOW_GAMES == await authenticated_psn_client.get_psnow_games(acc_info)
    http_get.assert_called_once()

@pytest.mark.asyncio
@pytest.mark.parametrize("backend_response", [
    {},
    {"data": {"included": "bad data"}},
    {"data": {"included": [{"id": "EDIN_CN242242_00", "type": "game"}]}},
    {"data": {"included": [{"id": "EDIN_CN242242_00", "type": "game", "attributes": "bad data"}]}},
    {"data": {"included": [{"id": "EDIN_CN242242_00", "attributes": {"name": "BioShock Collection"}}]}},
])
async def test_get_psplus_games_bad_format(
    http_get,
    user_account_info,
    authenticated_psn_client,
    backend_response,
):
    http_get.return_value = backend_response
    acc_info = user_account_info

    with pytest.raises(UnknownBackendResponse):
        await authenticated_psn_client.get_psplus_games(acc_info)
    http_get.assert_called_once()
