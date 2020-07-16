import asyncio
import binascii
import json
import logging
import pickle
import sys
from collections import defaultdict

from galaxy.api.plugin import Plugin, create_and_run_plugin
from galaxy.api.types import Authentication, NextStep, Achievement, UserPresence, PresenceState, SubscriptionGame, Subscription
from galaxy.api.consts import Platform, SubscriptionDiscovery
from galaxy.api.errors import ApplicationError, InvalidCredentials, UnknownError
from galaxy.api.jsonrpc import InvalidParams

import serialization
from cache import Cache
from http_client import AuthenticatedHttpClient
from psn_client import (
    CommunicationId, TitleId, TrophyTitles, UnixTimestamp,
    PSNClient, MAX_TITLE_IDS_PER_REQUEST, PLAYSTATION_PLUS,
    PLAYSTATION_NOW
)
from typing import Dict, List, Set, Iterable, Tuple, Optional, Any, AsyncGenerator
from version import __version__

from http_client import OAUTH_LOGIN_URL, OAUTH_LOGIN_REDIRECT_URL

AUTH_PARAMS = {
    "window_title": "Login to My PlayStation\u2122",
    "window_width": 536,
    "window_height": 675,
    "start_uri": OAUTH_LOGIN_URL,
    "end_uri_regex": "^" + OAUTH_LOGIN_REDIRECT_URL + ".*"
}

_CID_TIDS_DICT = Dict[TitleId, Set[CommunicationId]]
_TID_CIDS_DICT = Dict[CommunicationId, Set[TitleId]]
_TID_TROPHIES_DICT = Dict[TitleId, List[Achievement]]

TROPHIES_CACHE_KEY = "trophies"
COMMUNICATION_IDS_CACHE_KEY = "communication_ids"

class PSNPlugin(Plugin):
    def __init__(self, reader, writer, token):
        super().__init__(Platform.Psn, __version__, reader, writer, token)
        self._http_client = AuthenticatedHttpClient(self.lost_authentication, self.store_credentials)
        self._psn_client = PSNClient(self._http_client)
        self._trophies_cache = Cache()
        logging.getLogger("urllib3").setLevel(logging.FATAL)

    @property
    def _comm_ids_cache(self):
        return self.persistent_cache.setdefault(COMMUNICATION_IDS_CACHE_KEY, {})

    async def _do_auth(self, npsso):
        if not npsso:
            raise InvalidCredentials()

        await self._http_client.authenticate(npsso)
        user_id, user_name = await self._psn_client.async_get_own_user_info()

        return Authentication(user_id=user_id, user_name=user_name)

    async def authenticate(self, stored_credentials=None):
        stored_npsso = stored_credentials.get("npsso") if stored_credentials else None
        if not stored_npsso:
            return NextStep("web_session", AUTH_PARAMS)

        auth_info = await self._do_auth(stored_npsso)
        return auth_info

    async def pass_login_credentials(self, step, credentials, cookies):
        def get_npsso():
            for c in cookies:
                if c["name"] == "npsso" and c["value"]:
                    return c["value"]

        npsso = get_npsso()
        auth_info = await self._do_auth(npsso)
        return auth_info

    @staticmethod
    def _is_game(comm_id: List[CommunicationId]) -> bool:
        """Assumption: all games has communication id - otherwise it's DLC"""
        return comm_id != []

    async def update_communication_id_cache(self, title_ids: List[TitleId]) \
            -> Dict[TitleId, List[CommunicationId]]:
        async def updater(title_id_slice: Iterable[TitleId]):
            delta.update(await self._psn_client.async_get_game_communication_id_map(title_id_slice))

        delta: Dict[TitleId, List[CommunicationId]] = dict()
        await asyncio.gather(*[
            updater(title_ids[it:it + MAX_TITLE_IDS_PER_REQUEST])
            for it in range(0, len(title_ids), MAX_TITLE_IDS_PER_REQUEST)
        ])

        self._comm_ids_cache.update(delta)
        self.push_cache()
        return delta

    async def get_game_communication_ids(self, title_ids: List[TitleId]) -> Dict[TitleId, List[CommunicationId]]:
        result: Dict[TitleId, List[CommunicationId]] = dict()
        misses: Set[TitleId] = set()
        for title_id in title_ids:
            comm_ids: Optional[List[CommunicationId]] = self._comm_ids_cache.get(title_id)
            if comm_ids is not None:
                result[title_id] = comm_ids
            else:
                misses.add(title_id)

        if misses:
            result.update(await self.update_communication_id_cache(list(misses)))

        return result

    async def get_subscriptions(self) -> List[Subscription]:
        is_plus_active = await self._psn_client.get_psplus_status()
        return [Subscription(PLAYSTATION_PLUS, is_plus_active, None),
            Subscription(PLAYSTATION_NOW, None, None, SubscriptionDiscovery.USER_ENABLED)]

    async def get_subscription_games(self, subscription_name: str, context: Any) -> AsyncGenerator[List[SubscriptionGame], None]:
        account_info = await self._psn_client.get_account_info()
        if subscription_name == PLAYSTATION_PLUS:
            yield await self._psn_client.get_psplus_games(account_info)
        
        if subscription_name == PLAYSTATION_NOW:
            yield await self._psn_client.get_psnow_games(account_info)

    async def get_owned_games(self):
        async def filter_games(titles):
            comm_id_map = await self.get_game_communication_ids([t.game_id for t in titles])
            return [title for title in titles if self._is_game(comm_id_map[title.game_id])]

        return await filter_games(
            await self._psn_client.async_get_owned_games()
        )

    async def get_unlocked_achievements(self, game_id: str, context: Any) -> List[Achievement]:
        if not context:
            return []
        comm_ids: List[CommunicationId] = (await self.get_game_communication_ids([game_id]))[game_id]
        if not self._is_game(comm_ids):
            raise InvalidParams()
        return self._get_game_trophies_from_cache(comm_ids, context)[0]

    async def prepare_achievements_context(self, game_ids: List[str]) -> Any:
        games_cids = await self.get_game_communication_ids(game_ids)
        trophy_titles = await self._psn_client.get_trophy_titles()

        pending_cid_tids, pending_tid_cids, tid_trophies = self._process_trophies_cache(games_cids, trophy_titles)

        # process pending trophies
        requests = []
        for comm_id in pending_cid_tids.keys():
            timestamp = trophy_titles[comm_id]
            pending_tids = pending_cid_tids[comm_id]
            requests.append(self._import_trophies(comm_id, pending_tids, pending_tid_cids, tid_trophies, timestamp))

        await asyncio.gather(*requests)

        # update cache
        if requests:
            try:
                self.persistent_cache[TROPHIES_CACHE_KEY] = serialization.dumps(self._trophies_cache)
                self.push_cache()
            except (pickle.PicklingError, binascii.Error):
                logging.error("Can not serialize trophies cache")

        return trophy_titles

    def _process_trophies_cache(
        self,
        games_cids: Dict[TitleId, Iterable[CommunicationId]],
        trophy_titles: TrophyTitles
    ) -> Tuple[_CID_TIDS_DICT, _TID_CIDS_DICT, _TID_TROPHIES_DICT]:
        pending_cid_tids: _CID_TIDS_DICT = defaultdict(set)
        pending_tid_cids: _TID_CIDS_DICT = defaultdict(set)
        tid_trophies: _TID_TROPHIES_DICT = {}

        for title_id, comm_ids in games_cids.items():

            game_trophies, pending_comm_ids = self._get_game_trophies_from_cache(comm_ids, trophy_titles)

            if pending_comm_ids:
                for comm_id in pending_comm_ids:
                    pending_cid_tids[comm_id].add(title_id)
                pending_tid_cids[title_id].update(pending_comm_ids)
                tid_trophies[title_id] = game_trophies

        return pending_cid_tids, pending_tid_cids, tid_trophies

    def _get_game_trophies_from_cache(self, game_comm_ids, trophy_titles):
        """Process all communication ids for the game"""
        game_trophies: List[Achievement] = []
        pending_comm_ids: Set[CommunicationId] = set()
        for comm_id in set(game_comm_ids):
            last_update_time = trophy_titles.get(comm_id)
            if last_update_time is None:
                continue
            trophies = self._trophies_cache.get(comm_id, last_update_time)
            if trophies is None:
                pending_comm_ids.add(comm_id)
            else:
                game_trophies.extend(trophies)
        return game_trophies, pending_comm_ids

    async def _import_trophies(
        self,
        comm_id: CommunicationId,
        pending_tids: Set[TitleId],
        pending_tid_cids: _TID_CIDS_DICT,
        tid_trophies: _TID_TROPHIES_DICT,
        timestamp: UnixTimestamp
    ):
        def handle_error(error_):
            for tid_ in pending_tids:
                del pending_tid_cids[tid_]

        try:
            trophies: List[Achievement] = await self._psn_client.async_get_earned_trophies(comm_id)
            self._trophies_cache.update(comm_id, trophies, timestamp)
            while pending_tids:
                tid = pending_tids.pop()
                game_trophies = tid_trophies[tid]
                game_trophies.extend(trophies)
                pending_comm_ids = pending_tid_cids[tid]
                pending_comm_ids.remove(comm_id)
                if not pending_comm_ids:
                    # the game has already all comm ids processed
                    del pending_tid_cids[tid]
        except ApplicationError as error:
            handle_error(error)
        except Exception:
            logging.exception("Unhandled exception. Please report it to the plugin developers")
            handle_error(UnknownError())

    async def prepare_user_presence_context(self, user_ids: List[str]) -> Any:
        return await self._psn_client.async_get_friends_presences()

    async def get_user_presence(self, user_id: str, context: Any) -> UserPresence:
        for user in context:
            if user_id in user:
                return user[user_id]
        return UserPresence(PresenceState.Unknown)

    async def get_friends(self):
        return await self._psn_client.async_get_friends()

    async def shutdown(self):
        await self._http_client.logout()

    def handshake_complete(self):
        trophies_cache = self.persistent_cache.get(TROPHIES_CACHE_KEY)
        if trophies_cache is not None:
            try:
                self._trophies_cache = serialization.loads(trophies_cache)
            except (pickle.UnpicklingError, binascii.Error):
                logging.exception("Can not deserialize trophies cache")

        comm_ids_cache = self.persistent_cache.get(COMMUNICATION_IDS_CACHE_KEY)
        if comm_ids_cache:
            try:
                self.persistent_cache[COMMUNICATION_IDS_CACHE_KEY] = json.loads(comm_ids_cache)
            except json.JSONDecodeError:
                logging.exception("Can not deserialize communication ids cache")


def main():
    create_and_run_plugin(PSNPlugin, sys.argv)


if __name__ == "__main__":
    main()
