import pytest
from plugin import PSNClient, PSNPlugin
from unittest.mock import MagicMock
from http_client import AuthenticatedHttpClient
from tests.async_mock import AsyncMock


@pytest.fixture()
def access_token():
    return "access_token"


@pytest.fixture()
def npsso():
    return "npsso"


@pytest.fixture()
def stored_credentials(npsso):
    return {"npsso": npsso}


@pytest.fixture()
def account_id():
    return "accountId"


@pytest.fixture()
def online_id():
    return "onlineId"


@pytest.fixture()
def user_profile(online_id, account_id):
    return {"profile": {"onlineId": online_id, "accountId": account_id}}


@pytest.fixture()
def psplus_active_status():
    return 1


@pytest.fixture()
def user_profile_psplus(psplus_active_status):
    return {"profile": {"plus": psplus_active_status}}


@pytest.fixture()
def psplus_name():
    return "PlayStation PLUS"

@pytest.fixture()
def psnow_name():
    return "PlayStation Now"

@pytest.fixture()
def http_get(mocker):
    return mocker.patch(
        "plugin.AuthenticatedHttpClient.get",
        new_callable=AsyncMock
    )


@pytest.fixture()
async def psn_plugin():
    plugin = PSNPlugin(MagicMock(), MagicMock(), None)
    yield plugin

    await plugin.shutdown()


@pytest.fixture()
@pytest.mark.asyncio
async def authenticated_plugin(
    psn_plugin,
    access_token,
    stored_credentials,
    account_id,
    online_id,
    mocker
):
    mocker.patch.object(AuthenticatedHttpClient, "get_access_token", return_value=access_token, new_callable=AsyncMock)
    mocker.patch.object(PSNClient, "async_get_own_user_info", return_value=(account_id, online_id), new_callable=AsyncMock)

    await psn_plugin.authenticate(stored_credentials)
    return psn_plugin


@pytest.mark.asyncio
@pytest.fixture()
async def authenticated_psn_client(
    access_token,
    npsso,
    mocker
):

    mocker.patch.object(AuthenticatedHttpClient, "get_access_token", return_value=access_token, new_callable=AsyncMock)
    http_client = AuthenticatedHttpClient(None, None)
    await http_client.authenticate(npsso)

    yield PSNClient(http_client=http_client)

    await http_client.logout()
