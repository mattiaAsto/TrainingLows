"""
strava/client.py
----------------
Thin wrapper around the Strava API v3.
All methods accept an ``athlete_id`` and obtain a valid token automatically.

Reference: https://developers.strava.com/docs/reference/
"""

import requests
from typing import Optional

from .auth import get_valid_token

_BASE = "https://www.strava.com/api/v3"


# ── Internal request helper ────────────────────────────────────────────────────

def _get(athlete_id: int, path: str, params: Optional[dict] = None) -> dict | list:
    """
    Make an authenticated GET request to the Strava API.

    Args:
        athlete_id: The Strava athlete whose token will be used.
        path:       API path, e.g. ``/athlete``.
        params:     Optional query parameters.

    Returns:
        Parsed JSON response.

    Raises:
        RuntimeError: On non-2xx HTTP responses.
        LookupError:  If no token exists for the athlete.
    """
    token = get_valid_token(athlete_id)
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{_BASE}{path}", headers=headers, params=params, timeout=15)

    if not resp.ok:
        raise RuntimeError(
            f"Strava API error [{resp.status_code}] {path}: {resp.text}"
        )

    return resp.json()


# ── Athlete endpoints ──────────────────────────────────────────────────────────

def get_athlete(athlete_id: int) -> dict:
    """
    Fetch the authenticated athlete's profile.
    Scope required: ``read``

    Returns:
        DetailedAthlete object from Strava.
    """
    return _get(athlete_id, "/athlete")


def get_athlete_stats(athlete_id: int) -> dict:
    """
    Fetch totals and stats for the authenticated athlete.
    Scope required: ``read``

    Returns:
        ActivityStats object from Strava.
    """
    return _get(athlete_id, f"/athletes/{athlete_id}/stats")


def get_athlete_zones(athlete_id: int) -> dict:
    """
    Fetch heart-rate and power zones for the authenticated athlete.
    Scope required: ``read``

    Returns:
        Zones object from Strava.
    """
    return _get(athlete_id, "/athlete/zones")


# ── Activity endpoints ─────────────────────────────────────────────────────────

def get_activities(
    athlete_id: int,
    page: int = 1,
    per_page: int = 30,
    before: Optional[int] = None,
    after: Optional[int] = None,
) -> list:
    """
    List the authenticated athlete's activities.
    Scope required: ``activity:read``

    Args:
        athlete_id: The Strava athlete.
        page:       Page number (default 1).
        per_page:   Items per page, max 200 (default 30).
        before:     Unix timestamp — return activities before this time.
        after:      Unix timestamp — return activities after this time.

    Returns:
        List of SummaryActivity objects.
    """
    params = {"page": page, "per_page": per_page}
    if before:
        params["before"] = before
    if after:
        params["after"] = after

    return _get(athlete_id, "/athlete/activities", params=params)


def get_activity(athlete_id: int, activity_id: int) -> dict:
    """
    Fetch a single detailed activity.
    Scope required: ``activity:read``

    Returns:
        DetailedActivity object from Strava.
    """
    return _get(athlete_id, f"/activities/{activity_id}")


def get_activity_streams(
    athlete_id: int,
    activity_id: int,
    keys: Optional[list] = None,
) -> dict:
    """
    Fetch streams (time-series data) for a specific activity.
    Scope required: ``activity:read``

    Args:
        athlete_id:  The Strava athlete.
        activity_id: The activity.
        keys:        Data series to return. Defaults to
                     ``["time", "distance", "heartrate", "watts", "cadence"]``.

    Returns:
        Dict of StreamSet objects keyed by stream type.
    """
    if keys is None:
        keys = ["time", "distance", "heartrate", "watts", "cadence"]

    params = {
        "keys": ",".join(keys),
        "key_by_type": True,
    }
    return _get(athlete_id, f"/activities/{activity_id}/streams", params=params)


def get_activity_laps(athlete_id: int, activity_id: int) -> list:
    """
    Fetch laps for a specific activity.
    Scope required: ``activity:read``

    Returns:
        List of Lap objects.
    """
    return _get(athlete_id, f"/activities/{activity_id}/laps")


# ── Segment endpoints ──────────────────────────────────────────────────────────

def get_segment(athlete_id: int, segment_id: int) -> dict:
    """
    Fetch a single segment by ID.
    Scope required: ``read``

    Returns:
        DetailedSegment object from Strava.
    """
    return _get(athlete_id, f"/segments/{segment_id}")


def get_starred_segments(
    athlete_id: int, page: int = 1, per_page: int = 30
) -> list:
    """
    List segments starred by the authenticated athlete.
    Scope required: ``read``

    Returns:
        List of SummarySegment objects.
    """
    return _get(
        athlete_id,
        "/segments/starred",
        params={"page": page, "per_page": per_page},
    )