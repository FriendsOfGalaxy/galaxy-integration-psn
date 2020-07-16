from dataclasses import dataclass


@dataclass
class AccountUserInfo:
    region: str
    country: str
    language: str
    age: int


class PSNFreePlusStore:
    BASE_URL = 'https://store.playstation.com/'
    GAMES_CONTAINTER_URL = BASE_URL + 'valkyrie-api/{language}/{country}/{age}/container/{id}'
    SESSION = BASE_URL + 'kamaji/api/valkyrie_storefront/00_09_000/user/session'
    SUBSCRIPTION_DETAILS = BASE_URL + 'kamaji/api/valkyrie_storefront/00_09_000/gateway/store/v1/users/me/subscription/IP9102-NPIA90006_00'

    PSPLUS_URL = "https://browse.prod.gaikai.com/apollo1/v1/np/{country}/{language}"

    PSPLUS_FREEGAMES_REGION_STORE = {
        'SCEA': 'STORE-MSF77008-PSPLUSFREEGAMES',
        'SCEE': 'STORE-MSF75508-PLUSINSTANTGAME',
        'SCE-ASIA': 'STORE-MSF86012-PLUS_FTT_CONTENT',
        'SCEJ': 'PN.CH.JP-PN.CH.MIXED.JP-PSPLUSFREEPLAY',
        'SCEK': 'STORE-MSF86012-PLUS_FTT_KR'
    }

    def __init__(self, http_client, user: AccountUserInfo):
        self._http_client = http_client
        self.id = self.PSPLUS_FREEGAMES_REGION_STORE[user.region]
        self.country = user.country
        self.language = user.language[:2]
        self.age = 21 if user.age > 21 else user.age

    @property
    def games_container_url(self):
        return self.GAMES_CONTAINTER_URL.format(
            language=self.language, country=self.country, age=self.age, id=self.id)

    @property
    def psnow_games_url(self):
        return self.PSPLUS_URL.format(
            language=self.language, country=self.country)

    async def get_subscription_info(self):
        """This provides for information about user subscription data such as 'date_end'
        TODO: use it in plugin.get_subscriptions to provide extended info about subscritpion
        """
        await self._refresh_session()
        return await self._http_client.get(self.SUBSCRIPTION_DETAILS)

    async def _refresh_session(self):
        """TODO: generate auth code from logged-in user context"""
        body = 'code='  # + code
        res = await self._http_client.post(self.SESSION, data=body)
        return await res.json()
