"""
strava/auth.py
--------------
Handles all Strava OAuth2 operations:
  - Building the authorization URL
  - Exchanging a code for tokens
  - Refreshing expired access tokens
  - Persisting / loading tokens via SQLAlchemy
"""

import requests
from flask import current_app, url_for

from app import db
from app.models import StravaToken

_TOKEN_URL = "https://www.strava.com/oauth/token"
_AUTH_URL  = "https://www.strava.com/oauth/authorize"


# ── Public helpers ─────────────────────────────────────────────────────────────

def build_authorization_url() -> str:
    client_id = current_app.config["STRAVA_CLIENT_ID"]
    scopes    = current_app.config["STRAVA_SCOPES"]

    redirect_uri = url_for('strava.callback', _external=True, _scheme=current_app.config.get('PREFERRED_URL_SCHEME', 'http'))

    params = {
        "client_id":       client_id,
        "redirect_uri":    redirect_uri,
        "response_type":   "code",
        "approval_prompt": "auto",
        "scope":           scopes,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{_AUTH_URL}?{query}"


def exchange_code(code: str) -> StravaToken:
    """
    Exchange the OAuth authorization code for access + refresh tokens.
    Persists the result to the database and returns the StravaToken.

    Raises ``ValueError`` if the Strava response is unexpected.
    """
    data = _post_token(
        grant_type="authorization_code",
        code=code,
    )

    athlete_id = data["athlete"]["id"]

    token = StravaToken.query.filter_by(athlete_id=athlete_id).first()
    if token is None:
        token = StravaToken(athlete_id=athlete_id)
        db.session.add(token)

    token.update_from_response(data)
    token.scope = data.get("scope", "")
    db.session.commit()
    return token


def get_valid_token(athlete_id: int) -> str:
    """
    Return a valid access token for the given athlete, refreshing if needed.

    Raises ``LookupError``  if no token exists for this athlete.
    Raises ``RuntimeError`` if the refresh request fails.
    """
    token = StravaToken.query.filter_by(athlete_id=athlete_id).first()
    if token is None:
        raise LookupError(f"No Strava token found for athlete {athlete_id}")

    if token.is_expired:
        _refresh_token(token)

    return token.access_token


# ── Private helpers ────────────────────────────────────────────────────────────

def _refresh_token(token: StravaToken) -> None:
    """Refresh an expired token and persist the new values."""
    data = _post_token(
        grant_type="refresh_token",
        refresh_token=token.refresh_token,
    )
    token.update_from_response(data)
    db.session.commit()


def _post_token(**extra_params) -> dict:
    """
    POST to the Strava token endpoint.
    Always injects client_id and client_secret from app config.
    """
    payload = {
        "client_id":     current_app.config["STRAVA_CLIENT_ID"],
        "client_secret": current_app.config["STRAVA_CLIENT_SECRET"],
        **extra_params,
    }
    resp = requests.post(_TOKEN_URL, data=payload, timeout=10)

    if not resp.ok:
        raise RuntimeError(
            f"Strava token request failed [{resp.status_code}]: {resp.text}"
        )

    return resp.json()