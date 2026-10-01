"""Run one Strava activity poll, intended for a scheduled worker."""

from app import create_app
from app.strava.routes import sync_all_strava_users


if __name__ == '__main__':
    sync_all_strava_users(create_app())
