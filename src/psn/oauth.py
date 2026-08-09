import base64
import json
import logging
from typing import Any, Dict
from urllib.parse import parse_qs, urlencode, urlparse

from galaxy.api.errors import InvalidCredentials

from psn.constants import (
    OAUTH_AUTHORIZE_URL,
    OAUTH_CLIENT_BASIC,
    OAUTH_CLIENT_ID,
    OAUTH_REDIRECT_URI,
    OAUTH_SCOPE,
    OAUTH_TOKEN_URL,
)

logger = logging.getLogger(__name__)


def decode_jwt_payload(token: str) -> Dict[str, Any]:
    try:
        segment = token.split(".")[1]
        padding = "=" * (-len(segment) % 4)
        return json.loads(base64.urlsafe_b64decode(segment + padding))
    except (IndexError, ValueError, json.JSONDecodeError) as exc:
        raise InvalidCredentials("Could not read PlayStation account from token") from exc


def user_info_from_id_token(id_token: str) -> tuple[str, str]:
    payload = decode_jwt_payload(id_token)
    user_id = (
        payload.get("account_id")
        or payload.get("accountId")
        or payload.get("sub")
        or ""
    )
    user_name = (
        payload.get("online_id")
        or payload.get("onlineId")
        or payload.get("user_name")
        or user_id
    )
    if not user_id:
        raise InvalidCredentials("PlayStation token did not include account id")
    return str(user_id), str(user_name)


def _access_code_from_location(location: str) -> str:
    if not location or "code=" not in location:
        raise InvalidCredentials(
            "NPSSO token is invalid or expired. Sign in at store.playstation.com, "
            "then copy a fresh token from the ssocookie page."
        )

    if "redirect/" in location:
        query = location.split("redirect/", 1)[1]
    else:
        query = urlparse(location).query

    query = query.lstrip("?")
    values = parse_qs(query).get("code")
    if not values or not values[0].strip():
        raise InvalidCredentials(
            "NPSSO token is invalid or expired. Sign in at store.playstation.com, "
            "then copy a fresh token from the ssocookie page."
        )
    return values[0].strip()


async def exchange_npsso_for_access_code(http_client, npsso: str) -> str:
    query = urlencode(
        {
            "access_type": "offline",
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": OAUTH_SCOPE,
        }
    )
    url = f"{OAUTH_AUTHORIZE_URL}?{query}"
    response = await http_client.raw_request(
        "GET",
        url,
        allow_redirects=False,
        headers={"Cookie": f"npsso={npsso}"},
    )
    location = response.headers.get("Location", "")
    logger.debug("NPSSO authorize redirect: %s", location[:120] if location else "(none)")
    return _access_code_from_location(location)


async def exchange_access_code_for_tokens(http_client, access_code: str) -> Dict[str, Any]:
    response = await http_client.raw_request(
        "POST",
        OAUTH_TOKEN_URL,
        headers={
            "Authorization": OAUTH_CLIENT_BASIC,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=urlencode(
            {
                "code": access_code,
                "redirect_uri": OAUTH_REDIRECT_URI,
                "grant_type": "authorization_code",
                "token_format": "jwt",
            }
        ),
    )
    try:
        body = await response.json()
    except ValueError:
        body = {}
    if response.status >= 400 or "access_token" not in body:
        logger.warning("OAuth token exchange failed: %s", body)
        raise InvalidCredentials(
            "Could not exchange NPSSO token with PlayStation. "
            "Get a fresh token from the ssocookie page."
        )
    return body


async def exchange_npsso_for_tokens(http_client, npsso: str) -> Dict[str, Any]:
    access_code = await exchange_npsso_for_access_code(http_client, npsso)
    return await exchange_access_code_for_tokens(http_client, access_code)


async def refresh_oauth_tokens(http_client, refresh_token: str) -> Dict[str, Any]:
    """Trade a refresh token for a fresh access token (expires ~hourly)."""
    response = await http_client.raw_request(
        "POST",
        OAUTH_TOKEN_URL,
        headers={
            "Authorization": OAUTH_CLIENT_BASIC,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=urlencode(
            {
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "scope": OAUTH_SCOPE,
                "token_format": "jwt",
            }
        ),
    )
    try:
        body = await response.json()
    except ValueError:
        body = {}
    if response.status >= 400 or "access_token" not in body:
        logger.warning("OAuth token refresh failed: %s", body)
        raise InvalidCredentials("Could not refresh PlayStation session")
    return body
