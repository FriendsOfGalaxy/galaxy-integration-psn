OAUTH_LOGIN_REDIRECT_URL = "https://www.playstation.com/"

OAUTH_LOGIN_URL_TEMPLATE = (
    "https://web.np.playstation.com/api/session/v1/signin"
    "?redirect_uri=https://io.playstation.com/central/auth/login"
    "%3FpostSignInURL={redirect_url}"
    "%26cancelURL={redirect_url}"
    "&smcid=web:pdc"
)

OAUTH_LOGIN_URL = OAUTH_LOGIN_URL_TEMPLATE.format(
    redirect_url=OAUTH_LOGIN_REDIRECT_URL
)

NPSSO_COOKIE_URL = "https://ca.account.sony.com/api/v1/ssocookie"
PSN_STORE_URL = "https://store.playstation.com/"

# Galaxy matches end_uri after redirect; use the PSN homepage (200 OK), not a fake path.
NPSSO_AUTH_COMPLETE_URL = OAUTH_LOGIN_REDIRECT_URL
NPSSO_AUTH_COMPLETE_MARKER = "gog_psn_auth"
NPSSO_AUTH_QUERY_PARAM = "npsso"

# Must redirect to playstation.com (FriendsOfGalaxy pattern), not back to ssocookie.
REFRESH_COOKIES_URL = OAUTH_LOGIN_URL

OAUTH_AUTHORIZE_URL = "https://ca.account.sony.com/api/authz/v3/oauth/authorize"
OAUTH_TOKEN_URL = "https://ca.account.sony.com/api/authz/v3/oauth/token"
OAUTH_CLIENT_ID = "09515159-7237-4370-9b40-3806e67c0891"
OAUTH_REDIRECT_URI = "com.scee.psxandroid.scecompcall://redirect"
OAUTH_SCOPE = "psn:mobile.v2.core psn:clientapp"
OAUTH_CLIENT_BASIC = (
    "Basic MDk1MTUxNTktNzIzNy00MzcwLTliNDAtMzgwNmU2N2MwODkxOnVjUGprYTV0bnRCMktxc1A="
)

GAME_LIST_URL = (
    "https://web.np.playstation.com/api/graphql/v1/op"
    "?operationName=getPurchasedGameList"
    '&variables={{"isActive":true,"platform":["ps4","ps5"],'
    '"start":{start},"size":{size},"sortBy":"ACTIVE_DATE","sortDirection":"desc"}}'
    '&extensions={{"persistedQuery":{{"version":1,'
    '"sha256Hash":"827a423f6a8ddca4107ac01395af2ec0eafd8396fc7fa204aaf9b7ed2eefa168"}}}}'
)

PLAYED_GAME_LIST_URL = (
    "https://web.np.playstation.com/api/graphql/v1/op"
    "?operationName=getUserGameList"
    '&variables={{"categories":"ps4_game,ps5_native_game","limit":{size}}}'
    '&extensions={{"persistedQuery":{{"version":1,'
    '"sha256Hash":"e780a6d8b921ef0c59ec01ea5c5255671272ca0d819edb61320914cf7a78b3ae"}}}}'
)

PSN_PLUS_SUBSCRIPTIONS_URL = "https://store.playstation.com/subscriptions"

DEFAULT_PAGE_SIZE = 24
PLAYED_GAMES_PAGE_SIZE = 200
TROPHY_TITLES_PAGE_SIZE = 800
TROPHY_BATCH_SIZE = 5
# Below galaxy.http's connector limit (20) so queued requests don't
# exhaust the 30s total timeout while waiting for a connection; kept low
# because the HttpClient rate limiter paces requests globally anyway.
TROPHY_FETCH_CONCURRENCY = 4
FRIENDS_PAGE_SIZE = 2000

# Galaxy can request the owned-games import several times in quick succession
# after a reconnect; reuse in-session source fetches for this many seconds.
LIBRARY_SOURCE_MEMO_TTL = 300.0
# Store titles with no trophy activity re-check their trophy-set mapping at
# most this often (seconds); a first unlock bumps lastUpdatedDateTime anyway.
STORE_TROPHY_NEGATIVE_TTL = 7 * 24 * 3600.0
# The trophyTitles-for-titles endpoint accepts at most 5 npTitleIds per call.
STORE_TROPHY_BATCH_SIZE = 5
# Push fresh game times / trophies to Galaxy this often (seconds). Each poll
# costs ~2 requests (played list + trophy titles list) plus per-game fetches
# only for titles Sony reports as changed.
AUTO_UPDATE_INTERVAL = 600.0

USER_GAMES_API_BASE = "https://m.np.playstation.com/api/gamelist/v2/users"
TROPHY_API_BASE = "https://m.np.playstation.com/api/trophy"
USER_PROFILE_API_BASE = (
    "https://m.np.playstation.com/api/userProfile/v1/internal/users"
)
ACCOUNT_ME_URL = "https://dms.api.playstation.com/api/v1/devices/accounts/me"

# Legacy Sony sign-in page — blocked in embedded browsers.
AUTH_PARAMS = {
    "window_title": "Login to My PlayStation\u2122",
    "window_width": 536,
    "window_height": 675,
    "start_uri": OAUTH_LOGIN_URL,
    "end_uri_regex": "^" + OAUTH_LOGIN_REDIRECT_URL + ".*",
}
