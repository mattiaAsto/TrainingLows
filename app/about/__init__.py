from flask import Blueprint, redirect, session, url_for
from flask_login import current_user

from app.models import Athlete
from app.models import SupportMessage, SupportThread

about = Blueprint(
    "about",
    __name__,
    template_folder="templates",
)


@about.context_processor
def navigation_context():
    available_athletes = []
    selected_athlete = None
    if current_user.is_authenticated:
        if current_user.athlete_profile:
            available_athletes = [current_user.athlete_profile]
            selected_athlete = current_user.athlete_profile
        elif current_user.is_coach and current_user.coach_profile:
            available_athletes = list(current_user.coach_profile.athletes)
            selected_id = session.get('selected_athlete_id')
            selected_athlete = next((athlete for athlete in available_athletes if athlete.id == selected_id), None)
            selected_athlete = selected_athlete or (available_athletes[0] if available_athletes else None)
    return {
        'user': current_user,
        'selected_athlete': selected_athlete,
        'available_athletes': available_athletes,
        'support_unread_count': support_unread_count(),
    }


def support_unread_count():
    if not current_user.is_authenticated:
        return 0
    threads = SupportThread.query.filter_by(user_id=current_user.id).all()
    return sum(1 for thread in threads for message in thread.messages if message.is_admin and (thread.user_last_read_at is None or message.created_at > thread.user_last_read_at))


from . import routes
