from datetime import date, datetime, timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app import db
from app.models import Activity, DailyMetric, PhaseWeeklyTarget, TrainingObjective, TrainingPhase
from . import season, selected_athlete
from .services import get_or_create_season, suggest_phases


@season.route('/')
def season_home():
    athlete = selected_athlete()
    if athlete is None:
        abort(404)
    try:
        season_year = int(request.args.get('year', date.today().year))
    except (TypeError, ValueError):
        season_year = date.today().year
    if season_year < 2000 or season_year > 2100:
        season_year = date.today().year

    training_season = get_or_create_season(athlete, season_year, current_user.id)
    today = date.today()
    current_phase = next((phase for phase in training_season.phases if phase.start_date <= today <= phase.end_date), None)
    planning_end = max(
        [date(season_year, 12, 31)]
        + [objective.event_date for objective in training_season.objectives if objective.status == 'planned']
    )
    week_start = today - timedelta(days=today.weekday())
    current_target = None
    actual = {'duration_minutes': 0, 'distance_km': 0, 'sessions': 0, 'sleep_hours': None, 'readiness': None}
    if current_phase:
        current_target = PhaseWeeklyTarget.query.filter_by(phase_id=current_phase.id, week_start=week_start).first()
    activities = Activity.query.filter(
        Activity.athlete_id == athlete.id,
        Activity.date >= datetime.combine(week_start, datetime.min.time()),
        Activity.date < datetime.combine(week_start + timedelta(days=7), datetime.min.time()),
    ).all()
    actual['duration_minutes'] = round(sum((item.duration_seconds or 0) / 60 for item in activities), 1)
    actual['distance_km'] = round(sum(item.distance_km or 0 for item in activities), 1)
    actual['sessions'] = len(activities)
    recovery = DailyMetric.query.filter(
        DailyMetric.athlete_id == athlete.id,
        DailyMetric.metric_date >= week_start,
        DailyMetric.metric_date < week_start + timedelta(days=7),
    ).all()
    sleep_values = [item.sleep_duration_minutes / 60 for item in recovery if item.sleep_duration_minutes is not None]
    readiness_values = [item.readiness_score for item in recovery if item.readiness_score is not None]
    actual['sleep_hours'] = round(sum(sleep_values) / len(sleep_values), 1) if sleep_values else None
    actual['readiness'] = round(sum(readiness_values) / len(readiness_values), 1) if readiness_values else None
    db.session.commit()
    return render_template(
        'season.html',
        athlete=athlete,
        season=training_season,
        season_year=season_year,
        objectives=training_season.objectives,
        phases=training_season.phases,
        current_phase=current_phase,
        current_target=current_target,
        actual=actual,
        planning_end=planning_end,
    )


@season.route('/objective', methods=['POST'])
def create_objective():
    athlete = selected_athlete()
    if athlete is None:
        abort(404)
    try:
        event_date = date.fromisoformat(request.form.get('event_date', ''))
    except ValueError:
        flash('Please provide a valid objective date.', 'warning')
        return redirect(url_for('season.season_home'))

    try:
        season_year = int(request.form.get('season_year', event_date.year))
        distance = float(request.form.get('distance_km') or 0) or None
        target_time = int(request.form.get('target_time_seconds') or 0) or None
        target_pace = float(request.form.get('target_pace') or 0) or None
        target_power = float(request.form.get('target_power') or 0) or None
    except ValueError:
        flash('Please check the objective numeric fields.', 'warning')
        return redirect(url_for('season.season_home'))

    training_season = get_or_create_season(athlete, season_year, current_user.id)
    objective = TrainingObjective(
        season=training_season,
        created_by_id=current_user.id,
        name=request.form.get('name', '').strip(),
        objective_type=request.form.get('objective_type', 'race'),
        priority=request.form.get('priority', 'B'),
        sport=request.form.get('sport', 'running'),
        event_date=event_date,
        distance_km=distance,
        location=request.form.get('location', '').strip() or None,
        elevation_gain_m=float(request.form.get('elevation_gain_m') or 0) or None,
        terrain=request.form.get('terrain', '').strip() or None,
        target_time_seconds=target_time,
        target_pace=target_pace,
        target_power=target_power,
        notes=request.form.get('notes', '').strip() or None,
    )
    if not objective.name:
        flash('Objective name is required.', 'warning')
        return redirect(url_for('season.season_home', year=season_year))
    db.session.add(objective)
    db.session.commit()
    flash('Objective added. Review the suggested phases before applying them.', 'success')
    return redirect(url_for('season.season_home', year=season_year))


@season.route('/suggest-phases', methods=['POST'])
def generate_phase_draft():
    athlete = selected_athlete()
    if athlete is None:
        abort(404)
    try:
        season_year = int(request.form.get('season_year', date.today().year))
    except ValueError:
        season_year = date.today().year
    training_season = get_or_create_season(athlete, season_year, current_user.id)
    suggest_phases(training_season, current_user.id)
    db.session.commit()
    flash('A new editable phase draft was generated from the objectives.', 'success')
    return redirect(url_for('season.season_home', year=season_year))


def _objective_from_form(objective, include_planning_fields=True):
    try:
        objective.event_date = date.fromisoformat(request.form.get('event_date', ''))
        objective.distance_km = float(request.form.get('distance_km') or 0) or None
        objective.elevation_gain_m = float(request.form.get('elevation_gain_m') or 0) or None
        objective.target_time_seconds = int(request.form.get('target_time_seconds') or 0) or None
        objective.target_pace = float(request.form.get('target_pace') or 0) or None
        objective.target_power = float(request.form.get('target_power') or 0) or None
        objective.result_time_seconds = int(request.form.get('result_time_seconds') or 0) or None
        objective.result_placing = int(request.form.get('result_placing') or 0) or None
    except ValueError:
        return False
    objective.name = request.form.get('name', objective.name).strip() or objective.name
    objective.objective_type = request.form.get('objective_type', objective.objective_type)
    objective.priority = request.form.get('priority', objective.priority)
    objective.sport = request.form.get('sport', objective.sport)
    objective.location = request.form.get('location', '').strip() or None
    objective.terrain = request.form.get('terrain', '').strip() or None
    objective.notes = request.form.get('notes', '').strip() or None
    if include_planning_fields:
        objective.status = request.form.get('status', objective.status)
    return True


@season.route('/objective/<int:objective_id>/edit', methods=['GET', 'POST'])
def edit_objective(objective_id):
    athlete = selected_athlete()
    objective = TrainingObjective.query.get_or_404(objective_id)
    if athlete is None or objective.season.athlete_id != athlete.id:
        abort(403)
    if request.method == 'POST':
        if objective.status == 'completed':
            locked_date = objective.event_date
            locked_priority = objective.priority
            if not _objective_from_form(objective, include_planning_fields=False):
                flash('Please check the objective values.', 'warning')
                return redirect(url_for('season.edit_objective', objective_id=objective.id))
            objective.event_date = locked_date
            objective.priority = locked_priority
            objective.status = 'completed'
        elif not _objective_from_form(objective):
            flash('Please check the objective values.', 'warning')
            return redirect(url_for('season.edit_objective', objective_id=objective.id))
        db.session.commit()
        flash('Objective updated.', 'success')
        return redirect(url_for('season.season_home', year=objective.season.season_year))
    return render_template('objective_form.html', objective=objective)


@season.route('/objective/<int:objective_id>/delete', methods=['POST'])
def delete_objective(objective_id):
    athlete = selected_athlete()
    objective = TrainingObjective.query.get_or_404(objective_id)
    if athlete is None or objective.season.athlete_id != athlete.id:
        abort(403)
    if objective.status == 'completed':
        flash('Completed objectives are locked and cannot be deleted.', 'warning')
        return redirect(url_for('season.season_home', year=objective.season.season_year))
    season_year = objective.season.season_year
    db.session.delete(objective)
    db.session.commit()
    flash('Objective removed.', 'success')
    return redirect(url_for('season.season_home', year=season_year))


@season.route('/phase', methods=['POST'])
def create_phase():
    athlete = selected_athlete()
    if athlete is None:
        abort(404)
    try:
        season_year = int(request.form.get('season_year', date.today().year))
        start_date = date.fromisoformat(request.form.get('start_date', ''))
        end_date = date.fromisoformat(request.form.get('end_date', ''))
    except ValueError:
        flash('Please provide valid phase dates.', 'warning')
        return redirect(url_for('season.season_home'))
    if start_date > end_date:
        flash('Phase end date must be on or after its start date.', 'warning')
        return redirect(url_for('season.season_home', year=season_year))
    training_season = get_or_create_season(athlete, season_year, current_user.id)
    phase = TrainingPhase(
        season=training_season,
        created_by_id=current_user.id,
        name=request.form.get('name', '').strip() or 'Custom phase',
        phase_type='custom',
        start_date=start_date,
        end_date=end_date,
        color=request.form.get('color', '#6c757d'),
        description=request.form.get('description', '').strip() or None,
        generation_source='manual',
        is_manually_edited=True,
    )
    db.session.add(phase)
    db.session.commit()
    flash('Manual phase added.', 'success')
    return redirect(url_for('season.season_home', year=season_year))


@season.route('/phase/<int:phase_id>/edit', methods=['GET', 'POST'])
def edit_phase(phase_id):
    athlete = selected_athlete()
    phase = TrainingPhase.query.get_or_404(phase_id)
    if athlete is None or phase.season.athlete_id != athlete.id:
        abort(403)
    if request.method == 'POST':
        try:
            phase.start_date = date.fromisoformat(request.form.get('start_date', ''))
            phase.end_date = date.fromisoformat(request.form.get('end_date', ''))
        except ValueError:
            flash('Please provide valid phase dates.', 'warning')
            return redirect(url_for('season.edit_phase', phase_id=phase.id))
        if phase.start_date > phase.end_date:
            flash('Phase end date must be on or after its start date.', 'warning')
            return redirect(url_for('season.edit_phase', phase_id=phase.id))
        phase.name = request.form.get('name', phase.name).strip() or phase.name
        phase.phase_type = request.form.get('phase_type', phase.phase_type)
        phase.color = request.form.get('color', phase.color)
        phase.description = request.form.get('description', '').strip() or None
        phase.is_manually_edited = True
        phase.generation_source = 'manually_edited'
        db.session.commit()
        flash('Phase updated.', 'success')
        return redirect(url_for('season.season_home', year=phase.season.season_year))
    return render_template('phase_form.html', phase=phase)


@season.route('/phase/<int:phase_id>/target', methods=['POST'])
def save_weekly_target(phase_id):
    athlete = selected_athlete()
    phase = TrainingPhase.query.get_or_404(phase_id)
    if athlete is None or phase.season.athlete_id != athlete.id:
        abort(403)
    try:
        week_start = date.fromisoformat(request.form.get('week_start', ''))
        values = {
            'target_duration_minutes': int(request.form.get('target_duration_minutes') or 0) or None,
            'target_distance_km': float(request.form.get('target_distance_km') or 0) or None,
            'target_tss': float(request.form.get('target_tss') or 0) or None,
            'target_sleep_hours': float(request.form.get('target_sleep_hours') or 0) or None,
            'target_readiness': float(request.form.get('target_readiness') or 0) or None,
        }
    except ValueError:
        flash('Please check the weekly target values.', 'warning')
        return redirect(url_for('season.edit_phase', phase_id=phase.id))
    target = PhaseWeeklyTarget.query.filter_by(phase_id=phase.id, week_start=week_start).first()
    if target is None:
        target = PhaseWeeklyTarget(phase_id=phase.id, week_start=week_start)
        db.session.add(target)
    for key, value in values.items():
        setattr(target, key, value)
    target.focus = request.form.get('focus', '').strip() or None
    db.session.commit()
    flash('Weekly target saved.', 'success')
    return redirect(url_for('season.edit_phase', phase_id=phase.id))
