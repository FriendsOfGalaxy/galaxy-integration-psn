import pytest

from psn.auth import PSNAuthenticator


class FakeTokenHttp:
    def __init__(self, status=200, body=None):
        self._status = status
        self._body = body or {}
        self.requests = []
        self.access_token = None

    async def raw_request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs.get("data")))
        outer = self

        class Response:
            status = outer._status

            async def json(self):
                return outer._body

        return Response()

    def set_access_token(self, token):
        self.access_token = token


def make_authenticator(http, payload):
    stored = []
    authenticator = PSNAuthenticator(http, None, stored.append)
    authenticator._stored_payload = dict(payload)
    return authenticator, stored


@pytest.mark.asyncio
async def test_refresh_uses_refresh_token_grant():
    http = FakeTokenHttp(
        body={"access_token": "new-at", "refresh_token": "new-rt"}
    )
    authenticator, stored = make_authenticator(
        http, {"npsso": "np", "refresh_token": "old-rt", "access_token": "old-at"}
    )

    assert await authenticator.refresh_access_token() is True
    assert http.access_token == "new-at"
    assert "grant_type=refresh_token" in http.requests[0][2]
    assert stored[-1]["access_token"] == "new-at"
    assert stored[-1]["refresh_token"] == "new-rt"
    assert stored[-1]["npsso"] == "np"


@pytest.mark.asyncio
async def test_refresh_falls_back_to_npsso_when_grant_fails():
    http = FakeTokenHttp(status=400, body={"error": "invalid_grant"})
    authenticator, _ = make_authenticator(
        http, {"npsso": "np", "refresh_token": "dead-rt"}
    )
    npsso_calls = []

    async def fake_npsso_auth(npsso, from_token_file=False):
        npsso_calls.append(npsso)

    authenticator._authenticate_with_npsso = fake_npsso_auth

    assert await authenticator.refresh_access_token() is True
    assert npsso_calls == ["np"]


@pytest.mark.asyncio
async def test_refresh_returns_false_without_credentials():
    http = FakeTokenHttp(status=400)
    authenticator, _ = make_authenticator(http, {})

    assert await authenticator.refresh_access_token() is False


@pytest.mark.asyncio
async def test_reentrant_refresh_from_auth_flow_does_not_deadlock():
    # The NPSSO fallback makes API calls that can 401 and re-invoke the
    # refresher from the same task; that must return False, not deadlock.
    http = FakeTokenHttp(status=400, body={"error": "invalid_grant"})
    authenticator, _ = make_authenticator(
        http, {"npsso": "np", "refresh_token": "dead-rt"}
    )
    inner_results = []

    async def fake_npsso_auth(npsso, from_token_file=False):
        inner_results.append(await authenticator.refresh_access_token())

    authenticator._authenticate_with_npsso = fake_npsso_auth

    import asyncio

    outer = await asyncio.wait_for(authenticator.refresh_access_token(), timeout=2)

    assert outer is True  # NPSSO fallback "succeeded" (stub didn't raise)
    assert inner_results == [False]  # reentrant call bailed out immediately


@pytest.mark.asyncio
async def test_refresh_debounced_after_recent_success():
    http = FakeTokenHttp(
        body={"access_token": "new-at", "refresh_token": "new-rt"}
    )
    authenticator, _ = make_authenticator(
        http, {"refresh_token": "old-rt"}
    )

    assert await authenticator.refresh_access_token() is True
    assert await authenticator.refresh_access_token() is True
    # Second call hit the debounce window: no extra token request.
    assert len(http.requests) == 1
