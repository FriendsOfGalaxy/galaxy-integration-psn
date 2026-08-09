import asyncio
import logging
import sys
import time

if sys.version_info < (3, 13):
    raise ImportError(
        "This plugin requires GOG Galaxy 2.1.3 or newer (bundled Python 3.13). "
        f"Detected Python {sys.version_info.major}.{sys.version_info.minor}. "
        "Update GOG Galaxy from https://www.gog.com/galaxy, then reinstall the plugin."
    )

from typing import Any, List

from galaxy.api.consts import LicenseType, Platform
from galaxy.api.plugin import Plugin, create_and_run_plugin
from galaxy.api.types import (
    Achievement,
    Game,
    GameTime,
    LicenseInfo,
    Subscription,
    UserInfo,
)

from http_client import HttpClient
from psn.auth import PSNAuthenticator
from psn.client import PSNClient
from psn.constants import AUTO_UPDATE_INTERVAL
from version import __version__

logger = logging.getLogger(__name__)


class PSNPlugin(Plugin):
    def __init__(self, reader, writer, token):
        super().__init__(Platform.Psn, __version__, reader, writer, token)
        self._http_client = HttpClient()
        self._psn_client = PSNClient(self._http_client)
        self._authenticator = PSNAuthenticator(
            self._http_client,
            self._psn_client,
            self.store_credentials,
        )
        self._http_client.set_token_refresher(
            self._authenticator.refresh_access_token
        )
        self._owned_games_import: asyncio.Event | None = None
        self._psn_client.attach_persistent_cache(
            lambda: self.persistent_cache, self.push_cache
        )
        self._auto_update_task: asyncio.Task | None = None
        self._last_auto_update = time.monotonic()
        logging.getLogger("urllib3").setLevel(logging.FATAL)

    async def authenticate(self, stored_credentials=None):
        return await self._authenticator.authenticate(stored_credentials)

    async def pass_login_credentials(self, step, credentials, cookies):
        return await self._authenticator.complete_browser_login(
            step, credentials, cookies
        )

    async def get_subscriptions(self) -> List[Subscription]:
        # Galaxy's import collector expects owned games before subscriptions;
        # answering earlier trips "Invalid GameImportCollector transition
        # 'ImportedOwnedReleases' from state 'ImportingSubscriptions'" and the
        # sync's collected games are dropped.
        pending_owned_import = self._owned_games_import
        if pending_owned_import is not None and not pending_owned_import.is_set():
            try:
                await asyncio.wait_for(pending_owned_import.wait(), timeout=60)
            except TimeoutError:
                logger.warning(
                    "Owned games import still running; answering subscriptions anyway"
                )

        is_plus_active = await self._psn_client.get_psplus_status()
        return [
            Subscription(
                subscription_name="PlayStation PLUS",
                end_time=None,
                owned=is_plus_active,
            )
        ]

    async def get_subscription_games(
        self, subscription_name: str, context: Any
    ):
        # The SDK importer awaits this method and iterates the result, so it
        # must be a coroutine returning an async iterator, not an async
        # generator itself.
        try:
            games = await self._psn_client.get_subscription_games()
        except Exception:
            logger.warning("Could not fetch PS Plus games", exc_info=True)
            games = []

        async def pages():
            yield games

        return pages()

    async def _ensure_authenticated(self):
        if self._http_client._access_token:
            return
        payload = self._authenticator._stored_payload
        npsso = (payload or {}).get("npsso")
        if npsso:
            await self._authenticator._authenticate_with_npsso(npsso)

    async def get_owned_games(self):
        self._owned_games_import = asyncio.Event()
        try:
            await self._ensure_authenticated()
            titles = await self._psn_client.get_all_library_titles()
            return [
                Game(
                    game_id=title["titleId"],
                    game_title=title["name"],
                    dlcs=[],
                    license_info=LicenseInfo(LicenseType.SinglePurchase, None),
                )
                for title in titles
            ]
        finally:
            self._owned_games_import.set()
            self._psn_client.flush_cache()

    async def prepare_game_times_context(self, game_ids: List[str]) -> Any:
        await self._ensure_authenticated()
        return await self._psn_client.build_game_times_context(game_ids)

    async def get_game_time(self, game_id: str, context: Any) -> GameTime:
        if context and game_id in context:
            return context[game_id]
        return GameTime(game_id=game_id, time_played=None, last_played_time=None)

    async def prepare_achievements_context(self, game_ids: List[str]) -> Any:
        await self._ensure_authenticated()
        context = await self._psn_client.prepare_achievements_context(game_ids)
        self._last_achievements_context = context
        return context

    async def get_unlocked_achievements(
        self, game_id: str, context: Any
    ) -> List[Achievement]:
        if not context:
            return []
        return await self._psn_client.fetch_unlocked_achievements(game_id, context)

    def achievements_import_complete(self):
        self._psn_client.flush_cache()
        context = getattr(self, "_last_achievements_context", None)
        if context is None:
            return
        logger.info(
            "Trophy import finished: %d games with unlocks (%d total trophies), "
            "%d games empty",
            context.games_with_trophies,
            context.total_unlocked,
            context.games_empty,
        )

    async def get_friends(self) -> List[UserInfo]:
        await self._ensure_authenticated()
        try:
            return await self._psn_client.get_friends()
        except Exception:
            logger.warning("Could not fetch friends list", exc_info=True)
            return []

    def tick(self):
        if self._auto_update_task is not None and not self._auto_update_task.done():
            return
        if time.monotonic() - self._last_auto_update < AUTO_UPDATE_INTERVAL:
            return
        self._last_auto_update = time.monotonic()
        self._auto_update_task = asyncio.create_task(self._auto_update())

    async def _auto_update(self):
        """Push fresh game times and trophies between Galaxy's full imports."""
        if not self._http_client._access_token:
            return
        try:
            game_times = await self._psn_client.detect_game_time_updates()
            for game_time in game_times:
                self.update_game_time(game_time)

            trophy_updates = await self._psn_client.detect_trophy_updates()
            for game_id, achievement in trophy_updates:
                self.unlock_achievement(game_id, achievement)

            if game_times or trophy_updates:
                logger.info(
                    "Auto-update pushed %d game times and %d achievements",
                    len(game_times),
                    len(trophy_updates),
                )
            else:
                logger.info("Auto-update cycle: no changes")
            self._psn_client.flush_cache()
        except Exception:
            logger.warning("Auto-update cycle failed", exc_info=True)

    async def shutdown(self):
        if self._auto_update_task is not None:
            self._auto_update_task.cancel()
        self._psn_client.flush_cache()
        await self._authenticator.stop()
        await self._http_client.close()


def main():
    create_and_run_plugin(PSNPlugin, sys.argv)


if __name__ == "__main__":
    main()
