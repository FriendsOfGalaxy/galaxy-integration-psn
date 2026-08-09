import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, unquote, urlparse

from galaxy.api.errors import BackendTimeout, InvalidCredentials
from galaxy.api.types import Authentication, NextStep
from yarl import URL

from psn.client import PSNClient
from psn.constants import NPSSO_AUTH_QUERY_PARAM, NPSSO_COOKIE_URL
from psn.local_server import LocalAuthServer
from psn.oauth import (
    exchange_npsso_for_tokens,
    refresh_oauth_tokens,
    user_info_from_id_token,
)

logger = logging.getLogger(__name__)

SONY_ACCOUNT_URL = URL("https://ca.account.sony.com")

# Concurrent 401s all trigger refresh; treat a refresh completed this
# recently as still valid instead of hammering the token endpoint.
REFRESH_DEBOUNCE_SECONDS = 30.0


def npsso_from_end_uri(end_uri: str) -> Optional[str]:
    if not end_uri:
        return None
    parsed = urlparse(end_uri)
    for part in (parsed.query, parsed.fragment):
        if not part:
            continue
        values = parse_qs(part).get(NPSSO_AUTH_QUERY_PARAM)
        if values and values[0].strip():
            return unquote(values[0].strip())
    return None


def cookies_from_browser(cookies: list) -> Dict[str, str]:
    return {cookie["name"]: cookie["value"] for cookie in cookies}


def plugin_install_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def npsso_token_file_path() -> Path:
    return plugin_install_dir() / "npsso.token"


def read_npsso_token_file() -> Optional[str]:
    candidates = [
        npsso_token_file_path(),
        Path(os.environ.get("LOCALAPPDATA", "")) / "GOG.com" / "Galaxy" / "plugins" / "npsso.token",
    ]
    for path in candidates:
        if path.is_file():
            token = path.read_text(encoding="utf-8").strip()
            if token:
                logger.info("Using NPSSO token from %s", path)
                return token
    return None


class PSNAuthenticator:
    def __init__(self, http_client, psn_client: PSNClient, store_credentials_callback):
        self._http_client = http_client
        self._psn_client = psn_client
        self._store_credentials = store_credentials_callback
        self._local_server = LocalAuthServer()
        self._stored_payload: Dict[str, Any] = {}
        self._refresh_lock = asyncio.Lock()
        self._last_refresh = 0.0
        self._refresh_task: Optional[asyncio.Task] = None

    async def refresh_access_token(self) -> bool:
        """Renew the ~hourly access token; called by HttpClient on 401."""
        # The NPSSO fallback below makes API calls that can themselves 401
        # and re-enter this method from the same task; awaiting the held
        # (non-reentrant) lock would deadlock the plugin. Bail out and let
        # the auth flow's own fallbacks handle it.
        if self._refresh_task is asyncio.current_task():
            return False
        async with self._refresh_lock:
            if time.monotonic() - self._last_refresh < REFRESH_DEBOUNCE_SECONDS:
                return True
            self._refresh_task = asyncio.current_task()
            try:
                return await self._refresh_access_token_locked()
            finally:
                self._refresh_task = None

    async def _refresh_access_token_locked(self) -> bool:
        refresh_token = self._stored_payload.get("refresh_token")
        if refresh_token:
            try:
                tokens = await refresh_oauth_tokens(self._http_client, refresh_token)
                self._http_client.set_access_token(tokens["access_token"])
                payload = dict(self._stored_payload)
                payload["access_token"] = tokens.get("access_token")
                if tokens.get("refresh_token"):
                    payload["refresh_token"] = tokens["refresh_token"]
                if tokens.get("id_token"):
                    payload["id_token"] = tokens["id_token"]
                self._persist_credentials(payload)
                self._last_refresh = time.monotonic()
                logger.info("Access token refreshed")
                return True
            except Exception:
                logger.warning(
                    "Refresh token grant failed; re-authenticating with NPSSO",
                    exc_info=True,
                )

        npsso = (
            self._stored_payload.get("npsso")
            or (self._stored_payload.get("cookies") or {}).get("npsso")
            or read_npsso_token_file()
        )
        if not npsso:
            return False
        try:
            await self._authenticate_with_npsso(npsso)
        except Exception:
            logger.warning("NPSSO re-authentication failed", exc_info=True)
            return False
        self._last_refresh = time.monotonic()
        return True

    def configure_cookie_persistence(self):
        self._http_client.set_cookies_updated_callback(self._on_cookies_updated)

    def _on_cookies_updated(self, morsels):
        cookies = {morsel.key: morsel.value for morsel in morsels}
        payload = dict(self._stored_payload)
        payload["cookies"] = cookies
        if cookies.get("npsso"):
            payload["npsso"] = cookies["npsso"]
        if payload == self._stored_payload:
            return
        self._stored_payload = payload
        self._store_credentials(payload)

    def _persist_credentials(self, payload: Dict[str, Any]):
        self._stored_payload = dict(payload)
        self._store_credentials(payload)

    async def authenticate(
        self, stored_credentials: Optional[Dict[str, Any]] = None
    ):
        file_npsso = read_npsso_token_file()
        if file_npsso:
            return await self._authenticate_with_npsso(
                file_npsso, from_token_file=True
            )

        if stored_credentials:
            access_token = stored_credentials.get("access_token")
            if access_token:
                self._http_client.set_access_token(access_token)
            npsso = stored_credentials.get("npsso")
            if not npsso:
                cookies = stored_credentials.get("cookies") or {}
                npsso = cookies.get("npsso")
            if npsso:
                try:
                    return await self._authenticate_with_npsso(npsso)
                except InvalidCredentials:
                    logger.warning("Stored NPSSO token is invalid or expired")

        return await self._build_local_auth_step()

    async def _build_local_auth_step(self) -> NextStep:
        await self._local_server.start()
        logger.info(
            "Starting local browser auth (start_uri=%s)", self._local_server.base_url
        )
        return NextStep(
            "web_session",
            {
                "window_title": "Connect PlayStation Network",
                "window_width": 580,
                "window_height": 420,
                "start_uri": self._local_server.base_url,
                "end_uri_regex": self._local_server.end_uri_regex,
            },
        )

    async def complete_browser_login(
        self,
        step: str,
        credentials: Dict[str, str],
        cookies: list,
    ) -> Authentication:
        end_uri = credentials.get("end_uri", "")
        browser_cookies = cookies_from_browser(cookies)
        npsso = (
            self._local_server.captured_npsso
            or npsso_from_end_uri(end_uri)
            or browser_cookies.get(NPSSO_AUTH_QUERY_PARAM)
            or browser_cookies.get("npsso")
        )

        logger.info(
            "Browser auth callback (captured=%s, has_token=%s)",
            bool(self._local_server.captured_npsso),
            bool(npsso),
        )

        if not npsso:
            raise InvalidCredentials(
                "Paste your NPSSO token in the window, then click Connect."
            )

        try:
            return await self._authenticate_with_npsso(npsso)
        finally:
            await self._local_server.stop()

    async def stop(self):
        await self._local_server.stop()

    async def _authenticate_with_npsso(
        self, npsso: str, from_token_file: bool = False
    ) -> Authentication:
        if not npsso:
            raise InvalidCredentials()

        logger.info("Authenticating with NPSSO token")
        self._http_client.update_cookies({"npsso": npsso}, url=SONY_ACCOUNT_URL)

        try:
            await self._http_client.get(NPSSO_COOKIE_URL, silent=True, get_json=False)
            tokens = await exchange_npsso_for_tokens(self._http_client, npsso)
            self._http_client.set_access_token(tokens["access_token"])
            self._seed_account_id(tokens.get("id_token"))
            await self._http_client.refresh_cookies()
            auth = await self._build_authentication(tokens.get("id_token"))
        except InvalidCredentials:
            raise
        except Exception as exc:
            logger.exception("NPSSO authentication failed")
            if "timeout" in str(exc).lower():
                raise BackendTimeout("PlayStation Network request timed out") from exc
            message = (
                "Could not connect with npsso.token. Check that the token is fresh "
                "(sign in at store.playstation.com, then open the ssocookie page)."
                if from_token_file
                else "Could not verify NPSSO token with PlayStation"
            )
            raise InvalidCredentials(message) from exc

        self._persist_credentials(
            {
                "npsso": npsso,
                "cookies": self._current_cookies(),
                "access_token": tokens.get("access_token"),
                "refresh_token": tokens.get("refresh_token"),
                "id_token": tokens.get("id_token"),
            }
        )
        # Attach only after auth succeeds, so the handshake's intermediate
        # Set-Cookie responses don't flood Galaxy with store_credentials calls.
        self.configure_cookie_persistence()
        logger.info("NPSSO authentication succeeded for user %s", auth.user_name)
        return auth

    def _seed_account_id(self, id_token: Optional[str]):
        if not id_token:
            return
        try:
            account_id, _ = user_info_from_id_token(id_token)
            self._psn_client.set_account_id(account_id)
        except Exception:
            logger.debug("Could not read account id from id_token", exc_info=True)

    def _current_cookies(self) -> Dict[str, str]:
        return {
            morsel.key: morsel.value for morsel in self._http_client.cookie_jar
        }

    async def _build_authentication(self, id_token: Optional[str]) -> Authentication:
        try:
            user_id, user_name = await self._psn_client.get_own_user_info()
            if user_id:
                return Authentication(user_id=user_id, user_name=user_name)
        except Exception:
            logger.warning("Profile lookup failed, trying id_token fallback")

        if id_token:
            user_id, user_name = user_info_from_id_token(id_token)
            return Authentication(user_id=user_id, user_name=user_name)

        raise InvalidCredentials(
            "Connected to PlayStation but could not read your profile."
        )
