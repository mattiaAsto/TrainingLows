from flask import Blueprint, abort, current_app, redirect, request, url_for
from flask_login import current_user

strava = Blueprint(
    "strava", __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="strava/static"
)

@strava.before_request
def require_login():
    """Require login for all routes in this blueprint"""
    if not current_app.config.get('STRAVA_API_ACTIVE', False):
        abort(404)
    if request.endpoint == 'strava.webhook':
        return None
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login'))

from . import routes