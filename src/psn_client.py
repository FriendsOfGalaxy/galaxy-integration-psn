import asyncio
import logging
import re
from datetime import datetime, timezone
from functools import partial
from typing import Dict, List, NewType, Tuple

from galaxy.api.errors import UnknownBackendResponse
from galaxy.api.types import Achievement, Game, LicenseInfo, UserInfo, UserPresence, PresenceState, SubscriptionGame
from galaxy.api.consts import LicenseType
from http_client import paginate_url
from psn_store import PSNFreePlusStore, AccountUserInfo

# game_id_list is limited to 5 IDs per request
GAME_DETAILS_URL = "https://pl-tpy.np.community.playstation.net/trophy/v1/apps/trophyTitles" \
    "?npTitleIds={game_id_list}" \
    "&fields=@default" \
    "&npLanguage=en"

GAME_LIST_URL = "https://gamelist.api.playstation.com/v1/users/{user_id}/titles" \
    "?type=owned,played" \
    "&app=richProfile" \
    "&sort=-lastPlayedDate" \
    "&iw=240"\
    "&ih=240"\
    "&fields=@default"

TROPHY_TITLES_URL = "https://pl-tpy.np.community.playstation.net/trophy/v1/trophyTitles" \
    "?fields=@default" \
    "&platform=PS4" \
    "&npLanguage=en"

EARNED_TROPHIES_PAGE = "https://pl-tpy.np.community.playstation.net/trophy/v1/" \
    "trophyTitles/{communication_id}/trophyGroups/{trophy_group_id}/trophies?" \
    "fields=@default,trophyRare,trophyEarnedRate,trophySmallIconUrl,groupId" \
    "&visibleType=1" \
    "&npLanguage=en"

USER_INFO_URL = "https://pl-prof.np.community.playstation.net/userProfile/v1/users/{user_id}/profile2" \
    "?fields=accountId,onlineId"

USER_INFO_PSPLUS_URL = "https://pl-prof.np.community.playstation.net/userProfile/v1/users/{user_id}/profile2" \
    "?fields=plus"

DEFAULT_AVATAR_SIZE = "l"
FRIENDS_URL = "https://us-prof.np.community.playstation.net/userProfile/v1/users/{user_id}/friends/profiles2" \
    "?fields=accountId,onlineId,avatarUrls&avatarSizes={avatar_size_list}"

FRIENDS_WITH_PRESENCE_URL = "https://us-prof.np.community.playstation.net/userProfile/v1/users/{user_id}/friends/profiles2" \
    "?fields=accountId,onlineId,primaryOnlineStatus,presences(@titleInfo,lastOnlineDate)"

ACCOUNTS_URL = "https://accounts.api.playstation.com/api/v1/accounts/{user_id}"

DEFAULT_LIMIT = 100
MAX_TITLE_IDS_PER_REQUEST = 5

PLAYSTATION_PLUS = 'PlayStation PLUS'
PLAYSTATION_NOW = 'PlayStation Now'

CommunicationId = NewType("CommunicationId", str)
TitleId = NewType("TitleId", str)
UnixTimestamp = NewType("UnixTimestamp", int)
TrophyTitles = Dict[CommunicationId, UnixTimestamp]


def parse_timestamp(earned_date) -> UnixTimestamp:
    dt = datetime.strptime(earned_date, "%Y-%m-%dT%H:%M:%SZ")
    dt = datetime.combine(dt.date(), dt.time(), timezone.utc)
    return UnixTimestamp(int(dt.timestamp()))


def date_today():
    return datetime.today()


class PSNClient:
    def __init__(self, http_client):
        self._http_client = http_client

    @staticmethod
    async def _async(method, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(method, *args, **kwargs))

    async def fetch_paginated_data(
        self,
        parser,
        url,
        counter_name,
        limit=DEFAULT_LIMIT,
        *args,
        **kwargs
    ):
        response = await self._http_client.get(paginate_url(url=url, limit=limit), *args, **kwargs)
        if not response:
            return []

        try:
            total = int(response.get(counter_name, 0))
        except ValueError:
            raise UnknownBackendResponse()

        responses = [response] + await asyncio.gather(*[
            self._http_client.get(paginate_url(url=url, limit=limit, offset=offset), *args, **kwargs)
            for offset in range(limit, total, limit)
        ])

        try:
            return [rec for res in responses for rec in parser(res)]
        except Exception:
            logging.exception("Cannot parse data")
            raise UnknownBackendResponse()

    async def fetch_data(self, parser, *args, **kwargs):
        response = await self._http_client.get(*args, **kwargs)

        try:
            return parser(response)
        except Exception:
            logging.exception("Cannot parse data")
            raise UnknownBackendResponse()

    async def async_get_own_user_info(self):
        def user_info_parser(response):
            logging.debug(f'user profile data: {response}')
            return response["profile"]["accountId"], response["profile"]["onlineId"]

        return await self.fetch_data(
            user_info_parser,
            USER_INFO_URL.format(user_id="me")
        )

    async def get_psplus_status(self) -> bool:
        def user_subscription_parser(response):
            status = response["profile"]["plus"]
            if status in [0, 1, True, False]:
                return bool(status)
            raise TypeError

        return await self.fetch_data(
            user_subscription_parser,
            USER_INFO_PSPLUS_URL.format(user_id="me")
        )

    async def async_get_owned_games(self):
        def game_parser(title):
            return Game(
                game_id=title["titleId"],
                game_title=title["name"],
                dlcs=[],
                license_info=LicenseInfo(LicenseType.SinglePurchase, None)
            )

        def games_parser(response):
            return [
                game_parser(title) for title in response["titles"]
            ] if response else []

        return await self.fetch_paginated_data(
            games_parser,
            GAME_LIST_URL.format(user_id="me"),
            "totalResults"
        )

    async def async_get_game_communication_id_map(self, game_ids: List[TitleId]) \
            -> Dict[TitleId, List[CommunicationId]]:
        def communication_ids_parser(response):
            def get_comm_ids(trophy_titles):
                result = []
                for trophy_title in trophy_titles:
                    comm_id = trophy_title.get("npCommunicationId")
                    if comm_id is not None:
                        result.append(comm_id)
                return result

            try:
                return {
                    app["npTitleId"]: get_comm_ids(app["trophyTitles"])
                    for app in response["apps"]
                } if response else {}
            except (KeyError, IndexError):
                return {}

        mapping = await self.fetch_data(
            communication_ids_parser,
            GAME_DETAILS_URL.format(game_id_list=",".join(game_ids))
        )

        return {
            game_id: mapping.get(game_id, [])
            for game_id in game_ids
        }

    async def get_trophy_titles(self) -> TrophyTitles:
        def title_parser(title) -> Tuple[CommunicationId, UnixTimestamp]:
            return (title["npCommunicationId"], parse_timestamp((title.get("fromUser") or {})["lastUpdateDate"]))

        def titles_parser(response) -> List[Tuple[CommunicationId, UnixTimestamp]]:
            return [
                title_parser(title) for title in response.get("trophyTitles", [])
            ] if response else []

        result = await self.fetch_paginated_data(
            parser=titles_parser,
            url=TROPHY_TITLES_URL,
            counter_name="totalResults"
        )
        return dict(result)

    async def async_get_earned_trophies(self, communication_id) -> List[Achievement]:
        def trophy_parser(trophy) -> Achievement:
            return Achievement(
                achievement_id="{}_{}".format(communication_id, trophy["trophyId"]),
                achievement_name=str(trophy["trophyName"]),
                unlock_time=parse_timestamp(trophy["fromUser"]["earnedDate"])
            )

        def trophies_parser(response) -> List[Achievement]:
            return [
                trophy_parser(trophy) for trophy in response.get("trophies", [])
                if trophy.get("fromUser") and trophy["fromUser"].get("earned")
            ] if response else []

        return await self.fetch_data(trophies_parser, EARNED_TROPHIES_PAGE.format(
            communication_id=communication_id,
            trophy_group_id="all"))

    async def async_get_friends(self):
        def friend_info_parser(profile):

            avatar_url = None
            for avatar in profile["avatarUrls"]:
                avatar_url = avatar["avatarUrl"]

            return UserInfo(
                user_id=str(profile["accountId"]),
                user_name=str(profile["onlineId"]),
                avatar_url=avatar_url,
                profile_url=f"https://my.playstation.com/profile/{str(profile['onlineId'])}"
            )

        def friend_list_parser(response):
            logging.info(response)
            return [
                friend_info_parser(profile) for profile in response.get("profiles", [])
            ] if response else []

        return await self.fetch_paginated_data(
            friend_list_parser,
            FRIENDS_URL.format(user_id="me", avatar_size_list=DEFAULT_AVATAR_SIZE),
            "totalResults"
        )

    async def async_get_friends_presences(self):
        def friend_info_parser(profile):

            if profile["primaryOnlineStatus"] == "online":
                presence_state = PresenceState.Online
            else:
                presence_state = PresenceState.Offline

            game_title = game_id = None

            if "presences" in profile:
                for presence in profile["presences"]:
                    try:
                        if presence["onlineStatus"] == "online" and presence["platform"] == "PS4":
                            game_title = presence["titleName"]
                            game_id = presence["npTitleId"]
                    except:
                        continue

            return {profile['accountId']: UserPresence(presence_state, game_id, game_title)}

        def friends_with_presence_parser(response):
            return [
                friend_info_parser(profile) for profile in response.get("profiles", [])
            ] if response else []

        return await self.fetch_paginated_data(
            friends_with_presence_parser,
            FRIENDS_WITH_PRESENCE_URL.format(user_id="me"),
            "totalResults"
        )

    async def get_account_info(self) -> AccountUserInfo:
        def account_user_parser(data):
            td = date_today() - datetime.fromisoformat(data['dateOfBirth'])
            age = td.days // 365
            return AccountUserInfo(data['region'], data['legalCountry'], data['language'], age)

        return await self.fetch_data(account_user_parser, ACCOUNTS_URL.format(user_id='me'), silent=True)

    async def get_psplus_games(self, account_info: AccountUserInfo) -> List[SubscriptionGame]:
        logging.debug("Getting PSPlus Games")
        def games_parser(data):
            return [
                SubscriptionGame(
                    game_id=item['id'].split('-')[1],
                    game_title=item['attributes']['name']
                )
                for item in data['included']
                if item['type'] in ['game', 'game-related']
            ]

        store = PSNFreePlusStore(self._http_client, account_info)
        return await self.fetch_data(games_parser, store.games_container_url)

    async def get_psnow_games(self, account_info: AccountUserInfo) -> List[SubscriptionGame]:
        logging.debug("Getting PSNow Games")
        category_pattern = re.compile("^[A-Za-z0-9](?: - [A-Za-z0-9])?$")
        def games_parser(data):
            return [
                SubscriptionGame(
                    game_id=game['id'].split('-')[1],
                    game_title=game['name']
                )
                for category in data['categories']
                if category_pattern.match(category['name'])
                for game in category['games']
            ]

        store = PSNFreePlusStore(self._http_client, account_info)
        return await self.fetch_data(games_parser, store.psnow_games_url)