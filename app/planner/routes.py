from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import current_user

from app import db
from app.athlete_context import selected_athlete as get_current_athlete
from app.activity_catalog import ACTIVITY_DEFINITIONS, ACTIVITY_LABELS, ACTIVITY_UNITS
from app.models import Activity, PlannedActivity, get_activity_model

from . import planner


ACTIVITY_TYPE_MAP = {activity_type: get_activity_model(activity_type) for activity_type in ACTIVITY_DEFINITIONS}


@planner.context_processor
def global_injection_dictionary():

    return {
        "user": current_user,
        "activity_definitions": ACTIVITY_DEFINITIONS,
    }


@planner.route('/calendar/add', methods=['GET', 'POST'])
def add_entry():
    athlete = get_current_athlete()
    if not athlete:
        flash('You must have an athlete profile to manage calendar entries.', 'error')
        return redirect(url_for('main.calendar'))

    default_date = request.args.get('date') or datetime.now().strftime('%Y-%m-%d')
    entry_type = request.args.get('entry_type', request.form.get('entry_type', 'planned'))

    if request.method == 'POST':
        entry_type = request.form.get('entry_type', 'planned')
        activity_type = request.form.get('activity_type', 'running')
        title = request.form.get('title', '').strip() or f"{ACTIVITY_LABELS.get(activity_type, activity_type.title())} Session"
        date_value = request.form.get('date', datetime.now().date().isoformat())
        start_time = request.form.get('time', '08:00')
        duration_minutes = int(request.form.get('duration_minutes', 0) or 0)
        distance_km = float(request.form.get('distance_km', 0) or 0)
        intensity = request.form.get('intensity', 'moderate')
        description = request.form.get('description', '').strip()

        try:
            scheduled_dt = datetime.strptime(f"{date_value} {start_time}", '%Y-%m-%d %H:%M')
        except ValueError:
            scheduled_dt = datetime.combine(datetime.strptime(date_value, '%Y-%m-%d').date(), datetime.min.time().replace(hour=8))

        if entry_type == 'done':
            model_cls = ACTIVITY_TYPE_MAP.get(activity_type, get_activity_model(activity_type))
            session_activity = model_cls(
                athlete_id=athlete.id,
                title=title,
                activity_type=activity_type,
                duration_seconds=max(duration_minutes * 60, 0),
                distance_km=distance_km if ACTIVITY_UNITS.get(activity_type) == 'km' else None,
                calories_burned=int(request.form.get('calories', 0) or 0),
                elevation_gain_m=float(request.form.get('elevation_gain_m', 0) or 0),
                intensity=intensity,
                description=description or f"Completed {activity_type} session",
                date=scheduled_dt,
            )
            if activity_type == 'running':
                session_activity.pace_min_km = float(request.form.get('pace_min_km', 0) or 0)
                session_activity.surface = request.form.get('surface', 'road')
            elif activity_type == 'swimming':
                session_activity.pool_length_m = float(request.form.get('pool_length_m', 25) or 25)
                session_activity.strokes = request.form.get('strokes', 'freestyle')
                session_activity.water_type = request.form.get('water_type', 'pool')
            elif activity_type == 'cycling':
                session_activity.speed_km_h = float(request.form.get('speed_km_h', 0) or 0)
                session_activity.bike_type = request.form.get('bike_type', 'road')
                session_activity.terrain = request.form.get('terrain', 'road')
            elif activity_type == 'strength':
                session_activity.strenght_type = request.form.get('strength_type', 'general')

            db.session.add(session_activity)
            flash('Completed activity saved.', 'success')
        else:
            planned = PlannedActivity(
                athlete_id=athlete.id,
                title=title,
                activity_type=activity_type,
                planned_date=scheduled_dt,
                duration_seconds=max(duration_minutes * 60, 0),
                distance_km=distance_km if ACTIVITY_UNITS.get(activity_type) == 'km' else 0,
                intensity=intensity,
                description=description or f"Planned {activity_type} session",
            )
            db.session.add(planned)
            flash('Planned activity added.', 'success')

        db.session.commit()
        return redirect(url_for('main.calendar'))

    return render_template(
        'planner_form.html',
        default_date=default_date,
        athlete=athlete,
        entry_type=entry_type,
        entry={},
        is_edit=False,
    )


@planner.route('/calendar/entry/<string:entry_type>/<int:entry_id>', methods=['GET', 'POST'])
def edit_entry(entry_type, entry_id):
    athlete = get_current_athlete()
    if not athlete:
        flash('You must have an athlete profile to update workouts.', 'error')
        return redirect(url_for('main.calendar'))

    if entry_type == 'done':
        entry = Activity.query.filter_by(id=entry_id, athlete_id=athlete.id).first_or_404()
    else:
        entry = PlannedActivity.query.filter_by(id=entry_id, athlete_id=athlete.id).first_or_404()

    if request.method == 'POST':
        entry.title = request.form.get('title', entry.title).strip() or entry.title
        entry.activity_type = request.form.get('activity_type', entry.activity_type)
        entry.intensity = request.form.get('intensity', entry.intensity)
        entry.description = request.form.get('description', '').strip() or entry.description

        date_value = request.form.get('date', datetime.now().strftime('%Y-%m-%d'))
        start_time = request.form.get('time', '08:00')
        scheduled_dt = datetime.strptime(f"{date_value} {start_time}", '%Y-%m-%d %H:%M')

        if entry_type == 'done':
            entry.date = scheduled_dt
            entry.duration_seconds = max(int(request.form.get('duration_minutes', 0) or 0) * 60, 0)
            if hasattr(entry, 'distance_km'):
                entry.distance_km = float(request.form.get('distance_km', entry.distance_km or 0) or 0)
        else:
            entry.planned_date = scheduled_dt
            entry.duration_seconds = max(int(request.form.get('duration_minutes', 0) or 0) * 60, 0)
            if hasattr(entry, 'distance_km'):
                entry.distance_km = float(request.form.get('distance_km', entry.distance_km or 0) or 0)

        db.session.commit()
        flash('Entry updated.', 'success')
        return redirect(url_for('main.calendar'))

    return render_template('planner_form.html', entry=entry, entry_type=entry_type, athlete=athlete, is_edit=True)


@planner.route('/calendar/entry/<string:entry_type>/<int:entry_id>/delete', methods=['POST'])
def delete_entry(entry_type, entry_id):
    athlete = get_current_athlete()
    if not athlete:
        flash('You must be signed in as an athlete.', 'error')
        return redirect(url_for('main.calendar'))

    if entry_type == 'done':
        entry = Activity.query.filter_by(id=entry_id, athlete_id=athlete.id).first_or_404()
    else:
        entry = PlannedActivity.query.filter_by(id=entry_id, athlete_id=athlete.id).first_or_404()

    db.session.delete(entry)
    db.session.commit()
    flash('Entry removed.', 'success')
    return redirect(url_for('main.calendar'))


@planner.route('/api/calendar/entries')
def api_calendar_entries():
    athlete = get_current_athlete()
    if not athlete:
        return jsonify({'entries': []})

    date_value = request.args.get('date')
    if not date_value:
        return jsonify({'entries': []})

    entry_day = datetime.strptime(date_value, '%Y-%m-%d').date()
    start_dt = datetime.combine(entry_day, datetime.min.time())
    end_dt = datetime.combine(entry_day, datetime.max.time())

    done_entries = Activity.query.filter(
        Activity.athlete_id == athlete.id,
        Activity.date >= start_dt,
        Activity.date <= end_dt,
    ).all()

    planned_entries = PlannedActivity.query.filter(
        PlannedActivity.athlete_id == athlete.id,
        PlannedActivity.planned_date >= start_dt,
        PlannedActivity.planned_date <= end_dt,
        PlannedActivity.planned_date >= datetime.now(),
    ).all()

    items = []
    for row in done_entries:
        items.append({
            'id': row.id,
            'entry_type': 'done',
            'activity_type': row.activity_type,
            'title': row.title,
            'date': row.date.isoformat(),
            'duration_minutes': int((row.duration_seconds or 0) / 60),
            'distance_km': row.distance_km or 0,
            'intensity': row.intensity,
            'description': row.description or '',
        })

    for row in planned_entries:
        items.append({
            'id': row.id,
            'entry_type': 'planned',
            'activity_type': row.activity_type,
            'title': row.title,
            'date': row.planned_date.isoformat(),
            'duration_minutes': int((row.duration_seconds or 0) / 60),
            'distance_km': row.distance_km or 0,
            'intensity': row.intensity,
            'description': row.description or '',
        })

    return jsonify({'entries': sorted(items, key=lambda x: x['date'])})
