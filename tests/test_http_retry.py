import pytest
from galaxy.api.errors import AccessDenied

import http_client as http_client_module
from http_client import HttpClient

API_URL = "https://m.np.playstation.com/api/test/endpoint"


class FakeResponse:
    def __init__(self, status, body="{}", headers=None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    async def text(self):
        return self._body

    def raise_for_status(self):
        raise AccessDenied(f"HTTP {self.status}")


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = 0

    async def get(self, url, **kwargs):
        self.requests += 1
        return self._responses.pop(0)

    async def close(self):
        pass


def make_client(monkeypatch, responses):
    monkeypatch.setattr(http_client_module, "API_RATE_LIMIT_INTERVAL", 0.0)
    monkeypatch.setattr(http_client_module, "API_RETRY_BACKOFF", 0.0)
    client = HttpClient.__new__(HttpClient)
    client._access_token = "token"
    client._api_session = FakeSession(responses)
    client._rate_limiter = http_client_module.RateLimiter(0.0)
    return client


@pytest.mark.asyncio
async def test_retries_on_429_then_succeeds(monkeypatch):
    client = make_client(
        monkeypatch, [FakeResponse(429), FakeResponse(200, '{"ok": true}')]
    )
    assert await client.api_get(API_URL) == {"ok": True}
    assert client._api_session.requests == 2


@pytest.mark.asyncio
async def test_retries_on_403_then_succeeds(monkeypatch):
    client = make_client(
        monkeypatch, [FakeResponse(403), FakeResponse(200, '{"ok": true}')]
    )
    assert await client.api_get(API_URL) == {"ok": True}


def test_retry_after_capped_at_max_delay():
    response = FakeResponse(429, headers={"Retry-After": "3600"})
    assert (
        http_client_module._retry_delay(response, 0)
        == http_client_module.API_RETRY_MAX_DELAY
    )


@pytest.mark.asyncio
async def test_honors_retry_after_header(monkeypatch):
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(http_client_module.asyncio, "sleep", fake_sleep)
    client = make_client(
        monkeypatch,
        [
            FakeResponse(429, headers={"Retry-After": "7"}),
            FakeResponse(200, '{"ok": true}'),
        ],
    )
    assert await client.api_get(API_URL) == {"ok": True}
    assert 7.0 in sleeps


@pytest.mark.asyncio
async def test_raises_after_retries_exhausted(monkeypatch):
    attempts = http_client_module.API_MAX_RETRIES + 1
    client = make_client(monkeypatch, [FakeResponse(403)] * attempts)

    with pytest.raises(AccessDenied):
        await client.api_get(API_URL)
    assert client._api_session.requests == attempts


@pytest.mark.asyncio
async def test_no_retry_on_success(monkeypatch):
    client = make_client(monkeypatch, [FakeResponse(200, '{"value": 1}')])
    assert await client.api_get(API_URL) == {"value": 1}
    assert client._api_session.requests == 1


@pytest.mark.asyncio
async def test_404_with_not_found_ok_returns_none_without_retry(monkeypatch):
    client = make_client(monkeypatch, [FakeResponse(404)])
    assert await client.api_get(API_URL, not_found_ok=True) is None
    assert client._api_session.requests == 1


@pytest.mark.asyncio
async def test_401_refreshes_token_and_retries(monkeypatch):
    client = make_client(
        monkeypatch, [FakeResponse(401), FakeResponse(200, '{"ok": true}')]
    )
    refreshes = []

    async def refresher():
        refreshes.append(1)
        client._access_token = "fresh-token"
        return True

    client.set_token_refresher(refresher)

    assert await client.api_get(API_URL) == {"ok": True}
    assert len(refreshes) == 1
    assert client._api_session.requests == 2


@pytest.mark.asyncio
async def test_401_raises_when_refresh_fails(monkeypatch):
    client = make_client(monkeypatch, [FakeResponse(401)])

    async def refresher():
        return False

    client.set_token_refresher(refresher)

    with pytest.raises(AccessDenied):
        await client.api_get(API_URL)
    assert client._api_session.requests == 1


@pytest.mark.asyncio
async def test_401_refresh_only_attempted_once(monkeypatch):
    client = make_client(monkeypatch, [FakeResponse(401), FakeResponse(401)])
    refreshes = []

    async def refresher():
        refreshes.append(1)
        return True

    client.set_token_refresher(refresher)

    with pytest.raises(AccessDenied):
        await client.api_get(API_URL)
    assert len(refreshes) == 1
    assert client._api_session.requests == 2
