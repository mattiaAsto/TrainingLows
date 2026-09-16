from flask import session
from flask_login import current_user


def managed_athletes():
    if not current_user.is_authenticated:
        return []
    coach_profile = getattr(current_user, 'coach_profile', None)
    if current_user.is_coach and coach_profile:
        roster = list(coach_profile.athletes)
        athlete_profile = getattr(current_user, 'athlete_profile', None)
        if athlete_profile and athlete_profile not in roster:
            roster.insert(0, athlete_profile)
        return roster
    athlete_profile = getattr(current_user, 'athlete_profile', None)
    return [athlete_profile] if athlete_profile else []


def selected_athlete():
    roster = managed_athletes()
    if not roster:
        return None
    athlete_id = session.get('selected_athlete_id')
    if athlete_id:
        selected = next((athlete for athlete in roster if athlete.id == athlete_id), None)
        if selected:
            return selected
    return roster[0]


def athlete_is_visible(athlete):
    return athlete is not None and athlete in managed_athletes()
