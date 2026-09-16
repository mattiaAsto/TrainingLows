from datetime import date, timedelta

from app import db
from app.models import PhaseObjective, PhaseWeeklyTarget, TrainingPhase, TrainingSeason


PHASE_DEFAULTS = {
    'foundation': ('Foundation', '#6c757d'),
    'build': ('Build', '#198754'),
    'peak': ('Peak', '#fd7e14'),
    'taper': ('Taper', '#6f42c1'),
    'race': ('Race', '#dc3545'),
    'recovery': ('Recovery', '#0d6efd'),
}


def get_or_create_season(athlete, season_year, actor_id):
    season = TrainingSeason.query.filter_by(athlete_id=athlete.id, season_year=season_year).first()
    if season is None:
        season = TrainingSeason(
            athlete_id=athlete.id,
            season_year=season_year,
            name=f'{season_year} Season',
            generation_status='draft',
        )
        db.session.add(season)
        db.session.flush()
    return season


def suggest_phases(season, actor_id):
    """Create an editable draft around objectives without overwriting manual phases."""
    objectives = sorted(season.objectives, key=lambda objective: objective.event_date)
    if not objectives:
        return []

    planning_end = max(
        [date(season.season_year, 12, 31)]
        + [objective.event_date for objective in objectives if objective.status == 'planned']
    )
    generated = [phase for phase in season.phases if phase.generation_source == 'automatic' and not phase.is_manually_edited]
    for phase in generated:
        db.session.delete(phase)
    db.session.flush()

    phases = []
    for objective in objectives:
        race_date = objective.event_date
        windows = [
            ('foundation', race_date - timedelta(days=84), race_date - timedelta(days=43)),
            ('build', race_date - timedelta(days=42), race_date - timedelta(days=15)),
            ('taper', race_date - timedelta(days=14), race_date - timedelta(days=1)),
            ('race', race_date, race_date),
            ('recovery', race_date + timedelta(days=1), race_date + timedelta(days=14)),
        ]
        for phase_type, start_date, end_date in windows:
            start_date = max(start_date, date(season.season_year, 1, 1))
            end_date = min(end_date, planning_end)
            if start_date > end_date:
                continue
            name, color = PHASE_DEFAULTS[phase_type]
            phase = TrainingPhase(
                season_id=season.id,
                created_by_id=actor_id,
                name=name,
                phase_type=phase_type,
                start_date=start_date,
                end_date=end_date,
                color=color,
                generation_source='automatic',
                is_manually_edited=False,
            )
            db.session.add(phase)
            phases.append(phase)
    db.session.flush()
    for phase in phases:
        linked_objective = min(
            objectives,
            key=lambda objective: abs((objective.event_date - phase.start_date).days),
        )
        db.session.add(PhaseObjective(
            phase_id=phase.id,
            objective_id=linked_objective.id,
            role='primary' if linked_objective.priority == 'A' else 'secondary',
        ))
    season.generation_status = 'draft'
    return phases
