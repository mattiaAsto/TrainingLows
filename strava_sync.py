"""Run one Strava activity poll, intended for a scheduled worker."""

from app import create_app
from app.strava.routes import sync_all_strava_users


if __name__ == '__main__':
    app = create_app()
    if app.config.get('STRAVA_API_ACTIVE', False):
        sync_all_strava_users(app)
    else:
        print('Strava API is disabled (STRAVA_API_ACTIVE is not truthy); skipping sync.')
