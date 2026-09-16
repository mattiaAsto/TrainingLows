from flask import Blueprint, redirect, url_for
from flask_login import current_user

from app.athlete_context import managed_athletes, selected_athlete
from app.activity_catalog import ACTIVITY_DEFINITIONS

season = Blueprint(
    'season',
    __name__,
    template_folder='templates',
)


@season.context_processor
def navigation_context():
    roster = managed_athletes()
    return {
        'user': current_user,
        'available_athletes': roster,
        'selected_athlete': selected_athlete(),
        'activity_definitions': ACTIVITY_DEFINITIONS,
    }


@season.before_request
def require_login():
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login'))


from . import routes
