from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional
from urllib.parse import urlencode

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from config import (
    OAUTH_ACCESS_TOKEN_EXPIRE_SECONDS,
    OAUTH_REFRESH_TOKEN_EXPIRE_SECONDS,
    OIDC_ENABLED,
    OIDC_END_SESSION_ENDPOINT,
    OIDC_REDIRECT_URI,
    OIDC_RP_INITIATED_LOGOUT,
)
from decorators.auth import oauth
from endpoints.forms.identity import OAuth2RequestForm
from endpoints.responses.oauth import OIDCLogoutResponse, TokenResponse
from exceptions.auth_exceptions import (
    AuthCredentialsException,
    OIDCDisabledException,
    OIDCNotConfiguredException,
    UserDisabledException,
)
from handler.auth import oauth_handler, oidc_handler
from handler.database import db_user_handler
from logger.logger import log
from utils.router import APIRouter

router = APIRouter(
    tags=["auth"],
)


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(request: Request) -> Optional[OIDCLogoutResponse]:
    """Session logout endpoint

    Args:
        request (Request): Fastapi Request object

    Returns:
        Optional[dict]: When OIDC RP-Initiated Logout is enabled and the session
        contains an OIDC id_token, returns a dict with the OIDC end-session URL
        so the client can redirect the browser to log out of the OIDC provider.
    """

    id_token = request.session.get("oidc_id_token")
    request.session.clear()

    if OIDC_RP_INITIATED_LOGOUT and id_token:
        end_session_endpoint = OIDC_END_SESSION_ENDPOINT
        if not end_session_endpoint and oauth.openid:
            try:
                metadata = await oauth.openid.load_server_metadata()
                end_session_endpoint = metadata.get("end_session_endpoint", "")
            except Exception:
                log.warning(
                    "Failed to load OIDC server metadata for RP-Initiated Logout"
                )

        if end_session_endpoint:
            params = urlencode({"id_token_hint": id_token})
            return {"oidc_logout_url": f"{end_session_endpoint}?{params}"}

    return None


@router.post("/token")
async def token(form_data: Annotated[OAuth2RequestForm, Depends()]) -> TokenResponse:
    """OAuth2 token endpoint — only supports refresh_token grant.

    Args:
        form_data (Annotated[OAuth2RequestForm, Depends): Form Data with OAuth2 info

    Raises:
        HTTPException: Missing refresh token
        HTTPException: Invalid refresh token
        HTTPException: Invalid or unsupported grant type

    Returns:
        TokenResponse: TypedDict with the new generated token info
    """

    if form_data.grant_type != "refresh_token":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or unsupported grant type",
        )

    token = form_data.refresh_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing refresh token"
        )

    user, claims = await oauth_handler.consume_refresh_token(token)
    if not user or not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    if not user.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is disabled"
        )

    access_token = oauth_handler.create_access_token(
        data={
            "sub": user.username,
            "iss": "romm:oauth",
            "scopes": claims.get("scopes"),
        },
        expires_delta=timedelta(seconds=OAUTH_ACCESS_TOKEN_EXPIRE_SECONDS),
    )

    refresh_token = oauth_handler.create_refresh_token(
        data={
            "sub": user.username,
            "iss": "romm:oauth",
            "scopes": claims.get("scopes"),
        },
        expires_delta=timedelta(seconds=OAUTH_REFRESH_TOKEN_EXPIRE_SECONDS),
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",  # trunk-ignore(bandit/B105)
        "expires": OAUTH_ACCESS_TOKEN_EXPIRE_SECONDS,
        "refresh_expires": OAUTH_REFRESH_TOKEN_EXPIRE_SECONDS,
    }


# OIDC login and callback endpoints
@router.get("/login/openid")
async def login_via_openid(request: Request):
    """OIDC login endpoint

    Args:
        request (Request): Fastapi Request object

    Raises:
        OIDCDisabledException: OAuth is disabled
        OIDCNotConfiguredException: OAuth not configured

    Returns:
        RedirectResponse: Redirect to OIDC provider
    """

    if not OIDC_ENABLED:
        raise OIDCDisabledException

    if not oauth.openid:
        raise OIDCNotConfiguredException

    return await oauth.openid.authorize_redirect(request, OIDC_REDIRECT_URI)


@router.get("/oauth/openid")
async def auth_openid(request: Request):
    """OIDC callback endpoint

    Args:
        request (Request): Fastapi Request object

    Raises:
        OIDCDisabledException: OAuth is disabled
        OIDCNotConfiguredException: OAuth not configured
        AuthCredentialsException: Invalid credentials
        UserDisabledException: Auth is disabled

    Returns:
        RedirectResponse: Redirect to home page
    """

    if not OIDC_ENABLED:
        raise OIDCDisabledException

    if not oauth.openid:
        raise OIDCNotConfiguredException

    token = await oauth.openid.authorize_access_token(request)
    potential_user, _userinfo = (
        await oidc_handler.get_current_active_user_from_openid_token(token)
    )

    if not potential_user:
        raise AuthCredentialsException

    if not potential_user.enabled:
        raise UserDisabledException

    request.session["iss"] = "romm:auth"
    request.session["sub"] = potential_user.username
    if OIDC_RP_INITIATED_LOGOUT:
        request.session["oidc_id_token"] = token.get("id_token", "")

    # Update last login and active times
    now = datetime.now(timezone.utc)
    db_user_handler.update_user(
        potential_user.id, {"last_login": now, "last_active": now}
    )

    return RedirectResponse(url="/")


