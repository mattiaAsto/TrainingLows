from datetime import datetime, timedelta
import math

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import current_user

from app import db
from app.athlete_context import selected_athlete as get_current_athlete
from app.activity_catalog import ACTIVITY_DEFINITIONS, ACTIVITY_LABELS, ACTIVITY_UNITS, activity_specific_fields
from app.models import Activity, PlannedActivity, get_activity_model

from . import planner


ACTIVITY_TYPE_MAP = {activity_type: get_activity_model(activity_type) for activity_type in ACTIVITY_DEFINITIONS}


def parse_number(form, field_name, label, *, integer=False, minimum=None):
    raw_value = (form.get(field_name) or '').strip()
    if not raw_value:
        return None
    try:
        value = int(raw_value) if integer else float(raw_value)
    except ValueError as error:
        raise ValueError(f"{label} must be a valid {'whole number' if integer else 'number'}.") from error
    if not integer and not math.isfinite(value):
        raise ValueError(f"{label} must be a valid number.")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be at least {minimum}.")
    return value


def parse_duration_seconds(form):
    duration_minutes = parse_number(form, 'duration_minutes', 'Duration', minimum=0)
    if duration_minutes is None:
        raise ValueError('Duration is required.')
    return round(duration_minutes * 60)


def parse_scheduled_datetime(form):
    date_value = form.get('date', datetime.now().date().isoformat())
    start_time = form.get('time', '08:00')
    try:
        return datetime.strptime(f"{date_value} {start_time}", '%Y-%m-%d %H:%M')
    except ValueError as error:
        raise ValueError('Enter a valid date and time.') from error


def activity_specific_values(activity):
    data = dict(activity.specific_data or {})
    legacy_names = {'strength_type': 'strenght_type'}
    for field_name in activity_specific_fields(activity.activity_type):
        attribute_name = legacy_names.get(field_name, field_name)
        value = getattr(activity, attribute_name, None)
        if field_name not in data and value is not None:
            data[field_name] = value
    return data


def collect_specific_data(activity_type, form):
    data = {}
    for field_name, definition in activity_specific_fields(activity_type).items():
        raw_value = (form.get(f'specific_{field_name}') or '').strip()
        datatype = definition.get('datatype', 'text')
        if not raw_value and datatype != 'boolean':
            if definition.get('required'):
                raise ValueError(f"{definition.get('label', field_name)} is required.")
            continue
        try:
            if datatype == 'integer':
                value = int(raw_value)
            elif datatype == 'float':
                value = float(raw_value)
            elif datatype == 'boolean':
                value = raw_value.lower() in {'1', 'true', 'yes', 'on'}
            elif datatype == 'select':
                if raw_value not in definition.get('options', []):
                    raise ValueError
                value = raw_value
            else:
                value = raw_value
            if datatype == 'float' and not math.isfinite(value):
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError(f"{definition.get('label', field_name)} has an invalid value.")
        minimum = definition.get('min')
        maximum = definition.get('max')
        if datatype != 'boolean' and ((minimum is not None and value < minimum) or (maximum is not None and value > maximum)):
            raise ValueError(f"{definition.get('label', field_name)} is outside the allowed range.")
        data[field_name] = value
    return data


def apply_specific_data(activity, data):
    activity.specific_data = data or None
    legacy_names = {'strength_type': 'strenght_type'}
    for activity_type in ACTIVITY_DEFINITIONS:
        for field_name in activity_specific_fields(activity_type):
            attribute_name = legacy_names.get(field_name, field_name)
            if hasattr(activity, attribute_name):
                setattr(activity, attribute_name, None)
    for field_name, value in data.items():
        attribute_name = legacy_names.get(field_name, field_name)
        if hasattr(activity, attribute_name):
            setattr(activity, attribute_name, value)


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
        if activity_type not in ACTIVITY_DEFINITIONS:
            flash('Choose a valid activity type.', 'error')
            return render_template(
                'planner_form.html', default_date=default_date, athlete=athlete,
                entry_type=entry_type, entry={}, is_edit=False,
                form_values=request.form.to_dict(), specific_data_values={},
            )
        title = request.form.get('title', '').strip() or f"{ACTIVITY_LABELS.get(activity_type, activity_type.title())} Session"
        intensity = request.form.get('intensity', 'moderate')
        description = request.form.get('description', '').strip()
        try:
            scheduled_dt = parse_scheduled_datetime(request.form)
            duration_seconds = parse_duration_seconds(request.form)
            distance_km = parse_number(request.form, 'distance_km', 'Distance', minimum=0)
            specific_data = collect_specific_data(activity_type, request.form)
            if entry_type == 'done':
                activity_fields = {
                    'calories_burned': parse_number(request.form, 'calories', 'Calories', integer=True, minimum=0),
                    'elevation_gain_m': parse_number(request.form, 'elevation_gain_m', 'Elevation', minimum=0),
                    'average_heartrate': parse_number(request.form, 'average_heartrate', 'Average heart rate', minimum=0),
                }
                zone_times = {
                    f'timez{zone}_seconds': parse_number(
                        request.form, f'timez{zone}_seconds', f'Zone {zone} time',
                        integer=True, minimum=0,
                    )
                    for zone in range(1, 6)
                }
        except ValueError as error:
            flash(str(error), 'error')
            return render_template(
                'planner_form.html', default_date=default_date, athlete=athlete,
                entry_type=entry_type, entry={}, is_edit=False,
                form_values=request.form.to_dict(), specific_data_values={},
            )

        if entry_type == 'done':
            model_cls = ACTIVITY_TYPE_MAP.get(activity_type, get_activity_model(activity_type))
            session_activity = model_cls(
                athlete_id=athlete.id,
                title=title,
                activity_type=activity_type,
                duration_seconds=duration_seconds,
                distance_km=distance_km if ACTIVITY_UNITS.get(activity_type) == 'km' else None,
                **activity_fields,
                **zone_times,
                intensity=intensity,
                description=description or f"Completed {activity_type} session",
                date=scheduled_dt,
            )
            apply_specific_data(session_activity, specific_data)

            db.session.add(session_activity)
            flash('Completed activity saved.', 'success')
        else:
            planned = PlannedActivity(
                athlete_id=athlete.id,
                title=title,
                activity_type=activity_type,
                planned_date=scheduled_dt,
                duration_seconds=duration_seconds,
                distance_km=(distance_km or 0) if ACTIVITY_UNITS.get(activity_type) == 'km' else 0,
                intensity=intensity,
                description=description or f"Planned {activity_type} session",
                specific_data=specific_data or None,
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
        form_values={},
        specific_data_values={},
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
        activity_type = request.form.get('activity_type', entry.activity_type)
        if activity_type not in ACTIVITY_DEFINITIONS:
            flash('Choose a valid activity type.', 'error')
            return render_template(
                'planner_form.html', entry=entry, entry_type=entry_type,
                athlete=athlete, is_edit=True, form_values=request.form.to_dict(),
                specific_data_values=activity_specific_values(entry),
            )
        entry.title = request.form.get('title', entry.title).strip() or entry.title
        entry.activity_type = activity_type
        entry.intensity = request.form.get('intensity', entry.intensity)
        entry.description = request.form.get('description', '').strip() or None
        try:
            scheduled_dt = parse_scheduled_datetime(request.form)
            duration_seconds = parse_duration_seconds(request.form)
            distance_km = parse_number(request.form, 'distance_km', 'Distance', minimum=0)
            specific_data = collect_specific_data(entry.activity_type, request.form)
            if entry_type == 'done':
                activity_fields = {
                    'calories_burned': parse_number(request.form, 'calories', 'Calories', integer=True, minimum=0),
                    'elevation_gain_m': parse_number(request.form, 'elevation_gain_m', 'Elevation', minimum=0),
                    'average_heartrate': parse_number(request.form, 'average_heartrate', 'Average heart rate', minimum=0),
                    **{
                        f'timez{zone}_seconds': parse_number(
                            request.form, f'timez{zone}_seconds', f'Zone {zone} time',
                            integer=True, minimum=0,
                        )
                        for zone in range(1, 6)
                    },
                }
        except ValueError as error:
            flash(str(error), 'error')
            return render_template(
                'planner_form.html', entry=entry, entry_type=entry_type,
                athlete=athlete, is_edit=True, form_values=request.form.to_dict(),
                specific_data_values=activity_specific_values(entry),
            )
        if entry_type == 'done':
            apply_specific_data(entry, specific_data)
            for field_name, value in activity_fields.items():
                setattr(entry, field_name, value)
        else:
            entry.specific_data = specific_data or None

        if entry_type == 'done':
            entry.date = scheduled_dt
            entry.duration_seconds = duration_seconds
            if hasattr(entry, 'distance_km'):
                entry.distance_km = distance_km if ACTIVITY_UNITS.get(activity_type) == 'km' else None
        else:
            entry.planned_date = scheduled_dt
            entry.duration_seconds = duration_seconds
            if hasattr(entry, 'distance_km'):
                entry.distance_km = (distance_km or 0) if ACTIVITY_UNITS.get(activity_type) == 'km' else 0

        db.session.commit()
        flash('Entry updated.', 'success')
        return redirect(url_for('main.calendar'))

    return render_template(
        'planner_form.html', entry=entry, entry_type=entry_type, athlete=athlete,
        is_edit=True, form_values={}, specific_data_values=activity_specific_values(entry),
    )


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
            'specific_data': row.specific_data or {},
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
            'specific_data': row.specific_data or {},
        })

    return jsonify({'entries': sorted(items, key=lambda x: x['date'])})
