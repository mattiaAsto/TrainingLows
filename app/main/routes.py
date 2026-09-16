from flask import render_template, request, redirect, url_for, session, flash, jsonify, abort
from . import main
from app.models import *
from app import db
from app.activity_catalog import ACTIVITY_DEFINITIONS, ACTIVITY_COLORS, ACTIVITY_LABELS, ACTIVITY_TYPES, activity_value
from app.athlete_context import athlete_is_visible, managed_athletes as get_roster_for_current_user, selected_athlete as get_selected_athlete
from flask_login import current_user
from datetime import datetime, timedelta, date
from sqlalchemy import false
import os
import calendar as _calendar


ALL_ACTIVITY_TYPES = list(ACTIVITY_TYPES)


def _activity_value_for_chart(activity):
    return activity_value(activity)


def get_week_activities(date_start: datetime, date_stop: datetime, activity_type = "all"): #returns the list .reverse() -ed
    athlete_id = get_current_athlete_id()
    if not athlete_id:
        return []

    if activity_type == "all":
        activities = Activity.query.filter(
            Activity.athlete_id == athlete_id,
            Activity.date >= date_start,
            Activity.date < date_stop + timedelta(days=1)
            ).all()
    
    else:
        activities = Activity.query.filter(
            Activity.athlete_id == athlete_id,
            Activity.date >= date_start,
            Activity.date < date_stop + timedelta(days=1),
            Activity.activity_type == activity_type,
            ).all()
    
    return activities

def get_current_athlete_id():
    athlete = get_selected_athlete()
    return athlete.id if athlete else None


def get_week_planned_totals(athlete_id=None):
    """Load the logged athlete's planned training for the current week from the DB."""
    if athlete_id is None:
        athlete_id = get_current_athlete_id()

    totals = {activity_type: 0.0 for activity_type in ALL_ACTIVITY_TYPES}
    if not athlete_id:
        return totals

    now = datetime.now()
    start_of_week = date.today() - timedelta(days=date.today().weekday())
    start_dt = datetime.combine(start_of_week, datetime.min.time())
    end_dt = datetime.combine(start_of_week + timedelta(days=6), datetime.max.time())

    planned_rows = PlannedActivity.query.filter(
        PlannedActivity.athlete_id == athlete_id,
        PlannedActivity.planned_date >= start_dt,
        PlannedActivity.planned_date <= end_dt,
        PlannedActivity.planned_date >= now,
    ).all()

    for item in planned_rows:
        if item.activity_type not in totals:
            continue
        totals[item.activity_type] += activity_value(item, item.activity_type)

    return totals


def create_week_stats_from_activities(activities):
    total_distance = 0
    total_elev = 0
    total_cal = 0
    total_time_s = 0

    for activity in activities:
        total_distance += round(activity.distance_km, 1) if activity.distance_km else 0
        total_elev += activity.elevation_gain_m if activity.elevation_gain_m  else 0
        total_cal += activity.calories_burned if activity.calories_burned else 0
        total_time_s += activity.duration_seconds

    total_distance = f'{total_distance:.1f}'
    
    total_h = total_time_s // 3600
    total_min = (total_time_s - total_h * 3600) // 60

    total_time_formatted = f'{total_h}h {total_min}m'

    week_summary_dict = {
        'total_distance': total_distance,
        'total_time_formatted': total_time_formatted,
        'total_calories': total_cal,
        'total_elevation_gain': int(total_elev),
    }

    return week_summary_dict




@main.route('/test')
def test():

    print(ALL_ACTIVITY_TYPES)

    return jsonify("ciao")




@main.context_processor
def global_injection_dictionary():

    return {
        "user": current_user,
        "selected_athlete": get_selected_athlete(),
        "available_athletes": get_roster_for_current_user(),
        "activity_definitions": ACTIVITY_DEFINITIONS,
        "activity_colors": ACTIVITY_COLORS,
        "activity_labels": ACTIVITY_LABELS,
    }


@main.route("/")
def home():
    if not current_user.is_authenticated:
        return render_template("homeBlurredTemplate.html")

    today = date.today() #query until tomorrow becaus the request is exclusive 
    start_weekday = today - timedelta(days=today.weekday())

    week_activities = get_week_activities(start_weekday, today)
    week_activities = week_activities[::-1]

    planned_totals = get_week_planned_totals()
    actual_totals = {activity_type: 0.0 for activity_type in ALL_ACTIVITY_TYPES}
    for activity in week_activities:
        actual_totals[activity.activity_type] = actual_totals.get(activity.activity_type, 0) + activity_value(activity)

    weekly_breakdown = []
    for activity_type in ALL_ACTIVITY_TYPES:
        value = actual_totals.get(activity_type, 0)
        goal = planned_totals.get(activity_type, 0)
        unit = ACTIVITY_DEFINITIONS[activity_type]['unit']
        progress = (100 * value / goal) if goal else 0
        if progress > 100:
            progress = 100
        weekly_breakdown.append({
            'label': ACTIVITY_LABELS.get(activity_type, activity_type.title()),
            'value': value,
            'goal': goal,
            'unit': unit,
            'progress': progress,
            'color_class': activity_type,
            'color': ACTIVITY_COLORS.get(activity_type, '#6c757d'),
        })

    return render_template("home.html",
                           recent_activities = week_activities,
                           this_week = create_week_stats_from_activities(week_activities),
                           weekly_breakdown = weekly_breakdown,
                           )


def recovery_assessment(athlete_id, as_of=None):
    """Compare the latest seven recovery days with the preceding 28-day baseline."""
    as_of = as_of or date.today()
    recent_start = as_of - timedelta(days=6)
    baseline_start = as_of - timedelta(days=34)
    rows = DailyMetric.query.filter(
        DailyMetric.athlete_id == athlete_id,
        DailyMetric.metric_date >= baseline_start,
        DailyMetric.metric_date <= as_of,
    ).all()
    recent = [row for row in rows if row.metric_date >= recent_start]
    baseline = [row for row in rows if row.metric_date < recent_start]

    def average(items, field):
        values = [getattr(item, field) for item in items if getattr(item, field) is not None]
        return sum(values) / len(values) if values else None

    recent_values = {
        'readiness': average(recent, 'readiness_score'),
        'sleep': (average(recent, 'sleep_duration_minutes') / 60) if average(recent, 'sleep_duration_minutes') is not None else None,
        'resting_hr': average(recent, 'resting_hr'),
        'hrv': average(recent, 'hrv_ms'),
    }
    baseline_values = {
        'resting_hr': average(baseline, 'resting_hr'),
        'hrv': average(baseline, 'hrv_ms'),
    }
    alerts = []
    if recent_values['readiness'] is not None and recent_values['readiness'] < 60:
        alerts.append('Readiness is below 60.')
    if recent_values['sleep'] is not None and recent_values['sleep'] < 7:
        alerts.append('Average sleep is below 7 hours.')
    if recent_values['resting_hr'] is not None and baseline_values['resting_hr'] is not None and recent_values['resting_hr'] >= baseline_values['resting_hr'] + 5:
        alerts.append('Resting heart rate is elevated versus baseline.')
    if recent_values['hrv'] is not None and baseline_values['hrv'] is not None and recent_values['hrv'] <= baseline_values['hrv'] * 0.85:
        alerts.append('HRV is suppressed versus baseline.')
    return {
        'status': 'attention' if alerts else ('stable' if recent else 'missing'),
        'alerts': alerts,
        'recent': {key: round(value, 1) if value is not None else None for key, value in recent_values.items()},
        'baseline': {key: round(value, 1) if value is not None else None for key, value in baseline_values.items()},
    }


@main.route('/trainer-dashboard')
def trainer_dashboard():
    if not current_user.is_trainer:
        abort(403)
    athletes = get_roster_for_current_user()
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=7)
    cards = []

    for athlete in athletes:
        activities = Activity.query.filter(
            Activity.athlete_id == athlete.id,
            Activity.date >= datetime.combine(week_start, datetime.min.time()),
            Activity.date < datetime.combine(week_end, datetime.min.time()),
        ).all()
        planned = PlannedActivity.query.filter(
            PlannedActivity.athlete_id == athlete.id,
            PlannedActivity.planned_date >= datetime.combine(today, datetime.min.time()),
            PlannedActivity.planned_date < datetime.combine(today + timedelta(days=7), datetime.min.time()),
        ).order_by(PlannedActivity.planned_date.asc()).all()
        recovery_status = recovery_assessment(athlete.id, today)
        recovery = DailyMetric.query.filter(
            DailyMetric.athlete_id == athlete.id,
            DailyMetric.metric_date >= week_start,
            DailyMetric.metric_date < week_end,
        ).all()
        season = TrainingSeason.query.filter_by(athlete_id=athlete.id, season_year=today.year).first()
        current_phase = next((phase for phase in season.phases if phase.start_date <= today <= phase.end_date), None) if season else None
        next_objective = TrainingObjective.query.filter(
            TrainingObjective.season_id == season.id if season else false(),
            TrainingObjective.event_date >= today,
            TrainingObjective.status == 'planned',
        ).order_by(TrainingObjective.event_date.asc()).first()
        readiness_values = [item.readiness_score for item in recovery if item.readiness_score is not None]
        sleep_values = [item.sleep_duration_minutes / 60 for item in recovery if item.sleep_duration_minutes is not None]
        weekly_tss = round(sum(_estimate_activity_tss(item) for item in activities), 1)
        cards.append({
            'athlete': athlete,
            'is_self': athlete.id == current_user.id,
            'phase': current_phase,
            'objective': next_objective,
            'activities': len(activities),
            'planned': planned,
            'tss': weekly_tss,
            'readiness': round(sum(readiness_values) / len(readiness_values), 1) if readiness_values else None,
            'sleep': round(sum(sleep_values) / len(sleep_values), 1) if sleep_values else None,
            'needs_attention': recovery_status['status'] == 'attention',
            'recovery_status': recovery_status,
        })

    return render_template('trainer_dashboard.html', cards=cards, week_start=week_start, week_end=week_end - timedelta(days=1))


@main.route("/calendar")
def calendar():
    # The calendar content is loaded client-side for the selected view only.
    return render_template("calendar.html")


def _daily_metric_to_dict(metric):
    return {
        'id': metric.id,
        'entry_type': 'daily_metric',
        'title': 'Daily metrics',
        'date': metric.metric_date.isoformat(),
        'sleep_duration_minutes': metric.sleep_duration_minutes,
        'sleep_quality_score': metric.sleep_quality_score,
        'sleep_quality_label': metric.sleep_quality_label,
        'resting_hr': metric.resting_hr,
        'hrv_ms': metric.hrv_ms,
        'readiness_score': metric.readiness_score,
        'weight_kg': metric.weight_kg,
        'temperature_c': metric.temperature_c,
        'soreness_score': metric.soreness_score,
        'stress_score': metric.stress_score,
        'steps': metric.steps,
        'calories': metric.calories,
    }


def _current_athlete_or_redirect():
    athlete_id = get_current_athlete_id()
    return Athlete.query.get(athlete_id) if athlete_id else None


@main.route('/daily-metrics')
def daily_metrics():
    athlete = _current_athlete_or_redirect()
    if not athlete:
        return redirect(url_for('main.calendar'))
    metrics = DailyMetric.query.filter_by(athlete_id=athlete.id).order_by(DailyMetric.metric_date.desc()).limit(30).all()
    return render_template('daily_metrics.html', metrics=metrics, quality_labels=DailyMetric.QUALITY_LABELS)


@main.route('/daily-metrics/add', methods=['GET', 'POST'])
def add_daily_metric():
    athlete = _current_athlete_or_redirect()
    if not athlete:
        return redirect(url_for('main.calendar'))
    date_value = request.args.get('date') or request.form.get('metric_date') or date.today().isoformat()
    if request.method == 'POST':
        try:
            metric_date = datetime.strptime(request.form.get('metric_date', date.today().isoformat()), '%Y-%m-%d').date()
        except ValueError:
            metric_date = date.today()
        metric = DailyMetric.query.filter_by(athlete_id=athlete.id, metric_date=metric_date).first()
        if metric is None:
            metric = DailyMetric(athlete_id=athlete.id, metric_date=metric_date)
            db.session.add(metric)

        integer_fields = ('sleep_duration_minutes', 'sleep_quality_score', 'readiness_score', 'soreness_score', 'stress_score', 'steps', 'calories')
        float_fields = ('resting_hr', 'hrv_ms', 'weight_kg', 'temperature_c')
        for field in integer_fields:
            value = request.form.get(field, '').strip()
            setattr(metric, field, int(value) if value else None)
        for field in float_fields:
            value = request.form.get(field, '').strip()
            setattr(metric, field, float(value) if value else None)
        metric.notes = request.form.get('notes', '').strip() or None
        db.session.commit()
        flash('Daily metrics saved.', 'success')
        return redirect(url_for('main.daily_metric_detail', metric_id=metric.id))

    existing = DailyMetric.query.filter_by(athlete_id=athlete.id, metric_date=date_value).first()
    return render_template('daily_metric_form.html', metric=existing, metric_date=date_value, quality_labels=DailyMetric.QUALITY_LABELS)


@main.route('/daily-metrics/<int:metric_id>')
def daily_metric_detail(metric_id):
    athlete = _current_athlete_or_redirect()
    metric = DailyMetric.query.filter_by(id=metric_id, athlete_id=athlete.id if athlete else 0).first_or_404()
    return render_template('daily_metric_detail.html', metric=metric)


@main.route('/api/daily-metrics')
def api_daily_metrics():
    athlete_id = get_current_athlete_id()
    if not athlete_id:
        return jsonify({'metrics': []})
    try:
        start_date = datetime.strptime(request.args.get('start', ''), '%Y-%m-%d').date()
        end_date = datetime.strptime(request.args.get('end', ''), '%Y-%m-%d').date()
    except ValueError:
        start_date = date.today() - timedelta(days=6)
        end_date = date.today()
    metrics = DailyMetric.query.filter(
        DailyMetric.athlete_id == athlete_id,
        DailyMetric.metric_date >= start_date,
        DailyMetric.metric_date <= end_date,
    ).order_by(DailyMetric.metric_date.asc()).all()
    return jsonify({'metrics': [_daily_metric_to_dict(metric) for metric in metrics]})


def _activity_to_dict(a, entry_type='done'):
    date_value = getattr(a, 'date', None) or getattr(a, 'planned_date', None)
    return {
        'id': a.id,
        'entry_type': entry_type,
        'type': a.activity_type,
        'title': getattr(a, 'title', None) or a.activity_type,
        'distance': getattr(a, 'distance_km', None) or 0,
        'time': a.get_duration_formatted() if hasattr(a, 'get_duration_formatted') else None,
        'date': date_value.isoformat() if date_value else None,
        'status': 'planned' if entry_type == 'planned' else 'done',
        'is_future_planned': entry_type == 'planned' and getattr(a, 'planned_date', None) is not None and a.planned_date >= datetime.now(),
    }

def activity_query(start_dt, end_dt, activity_type=None):
    q = Activity.query
    athlete_id = get_current_athlete_id()
    if not athlete_id:
        return q.filter(false())
    q = q.filter(Activity.athlete_id == athlete_id)
    q = q.filter(Activity.date >= start_dt, Activity.date <= end_dt)
    if activity_type:
        q = q.filter(Activity.activity_type == activity_type)
    return q


def _timespan_bounds(view):
    today = date.today()
    if view == 'month':
        return date(today.year, today.month, 1), today
    if view == 'year':
        return date(today.year, 1, 1), date(today.year, 12, 31)
    return today - timedelta(days=6), today


@main.route('/api/calendar/week')
def api_calendar_week():
    # params: start YYYY-MM-DD (optional) -> start of week (Sunday)
    start_str = request.args.get('start')
    if start_str:
        try:
            start = datetime.fromisoformat(start_str).date()
        except Exception:
            start = date.today()
    else:
        start = date.today()

    # compute week starting Monday
    start_weekday = start.weekday()  # Monday=0
    monday = start - timedelta(days=start_weekday)

    week_days = []
    # optionally filter by athlete
    athlete_id = get_current_athlete_id()

    # load activities in range
    start_dt = datetime.combine(monday, datetime.min.time())
    end_dt = datetime.combine(monday + timedelta(days=6), datetime.max.time())
    activities = []
    planned_activities = []
    daily_metrics = []
    now = datetime.now()
    if athlete_id:
        activities = Activity.query.filter(Activity.athlete_id==athlete_id, Activity.date >= start_dt, Activity.date <= end_dt).all()
        planned_activities = PlannedActivity.query.filter(
            PlannedActivity.athlete_id==athlete_id,
            PlannedActivity.planned_date >= start_dt,
            PlannedActivity.planned_date <= end_dt,
            PlannedActivity.planned_date >= now,
        ).all()
        daily_metrics = DailyMetric.query.filter(
            DailyMetric.athlete_id == athlete_id,
            DailyMetric.metric_date >= monday,
            DailyMetric.metric_date <= monday + timedelta(days=6),
        ).all()

    for i in range(7):
        d = monday + timedelta(days=i)
        done_acts = []
        planned_day_acts = []
        metric_day = []
        for a in activities:
            if a.date.date() == d:
                done_acts.append(_activity_to_dict(a, 'done'))
        for a in planned_activities:
            if a.planned_date.date() == d:
                planned_day_acts.append(_activity_to_dict(a, 'planned'))
        for metric in daily_metrics:
            if metric.metric_date == d:
                metric_day.append(_daily_metric_to_dict(metric))
        done_acts = sorted(done_acts, key=lambda item: item.get('date') or '', reverse=False)
        planned_day_acts = sorted(planned_day_acts, key=lambda item: item.get('date') or '', reverse=False)
        week_days.append({
            'name': d.strftime('%A'),
            'date': d.isoformat(),
            'is_today': d == date.today(),
            'workouts': done_acts,
            'planned_workouts': planned_day_acts,
            'daily_metrics': metric_day,
        })

    # navigation helpers
    prev_week = (monday - timedelta(days=7)).isoformat()
    next_week = (monday + timedelta(days=7)).isoformat()

    return jsonify({'week_days': week_days, 'prev_week': prev_week, 'next_week': next_week})


@main.route('/api/calendar/phases')
def api_calendar_phases():
    athlete_id = get_current_athlete_id()
    if not athlete_id:
        return jsonify({'phases': []})
    try:
        start_date = date.fromisoformat(request.args.get('start', ''))
        end_date = date.fromisoformat(request.args.get('end', ''))
    except ValueError:
        start_date = date.today() - timedelta(days=6)
        end_date = date.today()
    phases = TrainingPhase.query.join(TrainingSeason).filter(
        TrainingSeason.athlete_id == athlete_id,
        TrainingPhase.start_date <= end_date,
        TrainingPhase.end_date >= start_date,
    ).order_by(TrainingPhase.start_date.asc()).all()
    objectives = TrainingObjective.query.join(TrainingSeason).filter(
        TrainingSeason.athlete_id == athlete_id,
        TrainingObjective.event_date >= start_date,
        TrainingObjective.event_date <= end_date,
    ).order_by(TrainingObjective.event_date.asc()).all()
    return jsonify({'phases': [{
        'id': phase.id,
        'name': phase.name,
        'phase_type': phase.phase_type,
        'start_date': phase.start_date.isoformat(),
        'end_date': phase.end_date.isoformat(),
        'color': phase.color,
        'description': phase.description,
    } for phase in phases], 'objectives': [{
        'id': objective.id,
        'name': objective.name,
        'date': objective.event_date.isoformat(),
        'priority': objective.priority,
        'sport': objective.sport,
    } for objective in objectives]})


@main.route('/api/graphs/activity_distribution')
def api_graphs_activity_distribution():
    view = request.args.get('view', 'week').lower()
    start_dt, end_dt = _timespan_bounds(view)
    activities = activity_query(start_dt, end_dt).all()

    totals = {tp: 0.0 for tp in ALL_ACTIVITY_TYPES}
    for activity in activities:
        if activity.activity_type in totals:
            totals[activity.activity_type] += _activity_value_for_chart(activity)

    labels = [tp.capitalize() for tp in totals.keys()]
    values = [round(v, 1) for v in totals.values()]

    return jsonify({'view': view, 'labels': labels, 'values': values})


@main.route('/api/graphs/intensity_distribution')
def api_graphs_intensity_distribution():
    view = request.args.get('view', 'week').lower()
    start_dt, end_dt = _timespan_bounds(view)
    activities = activity_query(start_dt, end_dt).all()

    zone_times = {'z1': 0, 'z2': 0, 'z3': 0, 'z4': 0, 'z5': 0}
    for activity in activities:
        zone_times['z1'] += getattr(activity, 'timez1_seconds', 0) or 0
        zone_times['z2'] += getattr(activity, 'timez2_seconds', 0) or 0
        zone_times['z3'] += getattr(activity, 'timez3_seconds', 0) or 0
        zone_times['z4'] += getattr(activity, 'timez4_seconds', 0) or 0
        zone_times['z5'] += getattr(activity, 'timez5_seconds', 0) or 0

    labels = ['Zone 1', 'Zone 2', 'Zone 3', 'Zone 4', 'Zone 5']
    values = [round(zone_times[z] / 3600.0, 1) for z in ['z1', 'z2', 'z3', 'z4', 'z5']]

    return jsonify({'view': view, 'labels': labels, 'values': values})


@main.route('/api/graphs/performance')
def api_graphs_performance():
    view = request.args.get('view', 'week').lower()
    start_dt, end_dt = _timespan_bounds(view)
    activities = activity_query(start_dt, end_dt).all()

    metrics = {
        'Distance (km)': 0.0,
        'Calories': 0,
        'Elevation (m)': 0.0,
        'Duration (h)': 0.0,
    }

    for activity in activities:
        metrics['Distance (km)'] += getattr(activity, 'distance_km', 0) or 0
        metrics['Calories'] += getattr(activity, 'calories_burned', 0) or 0
        metrics['Elevation (m)'] += getattr(activity, 'elevation_gain_m', 0) or 0
        metrics['Duration (h)'] += (getattr(activity, 'duration_seconds', 0) or 0) / 3600.0

    labels = list(metrics.keys())
    values = [round(v, 1) for v in metrics.values()]

    return jsonify({'view': view, 'labels': labels, 'values': values})


@main.route('/api/graphs/calories_by_activity')
def api_graphs_calories_by_activity():
    view = request.args.get('view', 'week').lower()
    start_dt, end_dt = _timespan_bounds(view)
    activities = activity_query(start_dt, end_dt).all()

    calories = {tp: 0 for tp in ALL_ACTIVITY_TYPES}
    for activity in activities:
        if activity.activity_type in calories:
            calories[activity.activity_type] += getattr(activity, 'calories_burned', 0) or 0

    labels = [tp.capitalize() for tp in calories.keys()]
    values = [calories[tp] for tp in calories.keys()]

    return jsonify({'view': view, 'labels': labels, 'values': values})


@main.route('/api/graphs/daily_metrics')
def api_graphs_daily_metrics():
    view = request.args.get('view', 'week').lower()
    start_dt, end_dt = _timespan_bounds(view)
    athlete_id = get_current_athlete_id()
    metrics = []
    if athlete_id:
        metrics = DailyMetric.query.filter(
            DailyMetric.athlete_id == athlete_id,
            DailyMetric.metric_date >= start_dt,
            DailyMetric.metric_date <= end_dt,
        ).order_by(DailyMetric.metric_date.asc()).all()

    return jsonify({
        'view': view,
        'labels': [metric.metric_date.isoformat() for metric in metrics],
        'sleep_hours': [round((metric.sleep_duration_minutes or 0) / 60.0, 2) if metric.sleep_duration_minutes is not None else None for metric in metrics],
        'resting_hr': [metric.resting_hr for metric in metrics],
        'hrv_ms': [metric.hrv_ms for metric in metrics],
        'readiness': [metric.readiness_score for metric in metrics],
        'sleep_quality': [metric.sleep_quality_score for metric in metrics],
    })


@main.route('/api/calendar/month')
def api_calendar_month():
    # params: year, month (optional)
    try:
        year = int(request.args.get('year', date.today().year))
        month = int(request.args.get('month', date.today().month))
    except Exception:
        year = date.today().year; month = date.today().month

    cal = _calendar.Calendar()
    month_weeks = []
    # date range
    first_day = date(year, month, 1)
    last_day = (first_day.replace(day=28) + timedelta(days=4))
    last_day = last_day - timedelta(days=last_day.day - 1)

    # prefetch activities
    athlete_id = get_current_athlete_id()

    # build weeks
    activities = []
    planned_activities = []
    daily_metrics = []
    now = datetime.now()
    if athlete_id:
        start_dt = datetime.combine(first_day - timedelta(days=7), datetime.min.time())
        end_dt = datetime.combine(first_day + timedelta(days=40), datetime.max.time())
        activities = Activity.query.filter(Activity.athlete_id==athlete_id, Activity.date >= start_dt, Activity.date <= end_dt).all()
        planned_activities = PlannedActivity.query.filter(
            PlannedActivity.athlete_id==athlete_id,
            PlannedActivity.planned_date >= start_dt,
            PlannedActivity.planned_date <= end_dt,
            PlannedActivity.planned_date >= now,
        ).all()
        daily_metrics = DailyMetric.query.filter(
            DailyMetric.athlete_id == athlete_id,
            DailyMetric.metric_date >= first_day - timedelta(days=7),
            DailyMetric.metric_date <= first_day + timedelta(days=40),
        ).all()

    week = []
    for d in cal.itermonthdates(year, month):
        done_acts = []
        planned_day_acts = []
        metric_day = []
        for a in activities:
            if a.date.date() == d:
                done_acts.append(_activity_to_dict(a))
        for a in planned_activities:
            if a.planned_date.date() == d:
                planned_day_acts.append(_activity_to_dict(a, 'planned'))
        for metric in daily_metrics:
            if metric.metric_date == d:
                metric_day.append(_daily_metric_to_dict(metric))
        day = {
            'date': d.isoformat(),
            'in_month': (d.month == month),
            'activities': done_acts,
            'planned_activities': planned_day_acts,
            'daily_metrics': metric_day,
        }
        week.append(day)
        if len(week) == 7:
            month_weeks.append(week)
            week = []

    # prev/next month
    prev_month_date = (first_day - timedelta(days=1)).replace(day=1)
    next_month_date = (first_day.replace(day=28) + timedelta(days=4)).replace(day=1)

    return jsonify({
        'calendar_month_weeks': month_weeks,
        'year': year,
        'month': month,
        'prev_month': {'year': prev_month_date.year, 'month': prev_month_date.month},
        'next_month': {'year': next_month_date.year, 'month': next_month_date.month}
    })


@main.route('/api/calendar/year')
def api_calendar_year():
    try:
        year = int(request.args.get('year', date.today().year))
    except Exception:
        year = date.today().year

    athlete_id = get_current_athlete_id()

    months = []
    for m in range(1,13):
        # aggregate simple sums
        total_distance = 0
        elevation_gain = 0
        count = 0
        metric_count = 0
        if athlete_id:
            start_dt = datetime(year, m, 1)
            # naive end day
            end_dt = (start_dt.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            acts = Activity.query.filter(Activity.athlete_id==athlete_id, Activity.date >= start_dt, Activity.date <= end_dt).all()
            for a in acts:
                total_distance += getattr(a, 'distance_km', 0) or 0
                elevation_gain += getattr(a, 'elevation_gain_m', 0) or 0
            count = len(acts)
            metric_count = DailyMetric.query.filter(
                DailyMetric.athlete_id == athlete_id,
                DailyMetric.metric_date >= date(year, m, 1),
                DailyMetric.metric_date <= date(year, m, _calendar.monthrange(year, m)[1]),
            ).count()
        months.append({'name': datetime(year, m, 1).strftime('%b'), 'distance': f'{total_distance:.1f}', 'activity_count': count, 'metric_count': metric_count, 'elevation': f'{elevation_gain:.0f}'})

    return jsonify({'year': year, 'months': months})


@main.route("/graphs")
def graphs():
    # Graph data is loaded asynchronously via AJAX when the page renders.
    return render_template("graphs.html", weekly_data_array=[])


@main.route('/api/graphs/week')
def api_graphs_week():
    # return same structure as graphs() but as JSON
    weekly_data_array = []
    next_sunday = date.today() + timedelta(days=6-(date.today().weekday()))
    for activity_type in ALL_ACTIVITY_TYPES:
        weekly_data = { 'activitytype': activity_type, 'labels': [], 'distances': [] }
        for i in range(9,-1,-1):
            stop = next_sunday + timedelta(weeks=-i)
            start = next_sunday + timedelta(weeks=-(i+1)) + timedelta(days=1)
            week_activities = get_week_activities(start, stop, activity_type)
            distance = float(create_week_stats_from_activities(week_activities)["total_distance"] or 0)
            weekly_data['labels'].append(stop.strftime('%Y-%m-%d'))
            weekly_data['distances'].append(distance)
        weekly_data_array.append(weekly_data)
    return jsonify({'data': weekly_data_array})


@main.route('/api/graphs/month')
def api_graphs_month():
    # params: year, month
    try:
        year = int(request.args.get('year', date.today().year))
        month = int(request.args.get('month', date.today().month))
    except Exception:
        year = date.today().year; month = date.today().month

    # days in month
    _, ndays = _calendar.monthrange(year, month)

    result = []
    for activity_type in ALL_ACTIVITY_TYPES:
        row = { 'activitytype': activity_type, 'labels': [], 'distances': [] }
        for d in range(1, ndays+1):
            start_dt = datetime(year, month, d)
            acts = get_week_activities(start_dt, start_dt, activity_type)
            s = 0
            for a in acts:
                s += _activity_value_for_chart(a)
            row['labels'].append(start_dt.strftime('%Y-%m-%d'))
            row['distances'].append(round(s, 1))
        result.append(row)
    return jsonify({'year': year, 'month': month, 'data': result})


@main.route('/api/graphs/year')
def api_graphs_year():
    try:
        year = int(request.args.get('year', date.today().year))
    except Exception:
        year = date.today().year

    result = []
    for activity_type in ALL_ACTIVITY_TYPES:
        row = { 'activitytype': activity_type, 'labels': [], 'distances': [] }
        for m in range(1,13):
            start_dt = datetime(year, m, 1)
            # naive end of month
            end_dt = (start_dt.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            acts = get_week_activities(start_dt, end_dt, activity_type)
            s = 0
            for a in acts:
                s += _activity_value_for_chart(a)
            row['labels'].append(start_dt.strftime('%b'))
            row['distances'].append(round(s,1))
        result.append(row)
    return jsonify({'year': year, 'data': result})


@main.route("/analysis")
def analysis():
    return render_template("analysis_dashboard.html")


def _estimate_activity_tss(activity):
    """Estimate TSS when the activity has no persisted training-load score."""
    duration_hours = (activity.duration_seconds or 0) / 3600.0
    if duration_hours <= 0:
        return 0.0

    zone_factors = (0.50, 0.65, 0.80, 0.95, 1.10)
    zone_seconds = [getattr(activity, f'timez{zone}_seconds', 0) or 0 for zone in range(1, 6)]
    zone_total = sum(zone_seconds)
    if zone_total > 0:
        weighted_intensity = sum(seconds * factor for seconds, factor in zip(zone_seconds, zone_factors)) / zone_total
    else:
        weighted_intensity = {'low': 0.55, 'moderate': 0.70, 'high': 0.85}.get(activity.intensity, 0.70)

    return duration_hours * (weighted_intensity ** 2) * 100.0


def _ewma(previous, value, time_constant):
    return previous + (value - previous) / time_constant


@main.route('/api/analysis')
def api_analysis():
    try:
        range_days = int(request.args.get('days', 90))
    except (TypeError, ValueError):
        range_days = 90
    if range_days not in (30, 90, 365):
        range_days = 90

    athlete_id = get_current_athlete_id()
    end_date = date.today()
    start_date = end_date - timedelta(days=range_days - 1)
    # Load enough history to seed the 42-day chronic-load EWMA at the range boundary.
    load_start_date = start_date - timedelta(days=42)
    start_dt = datetime.combine(load_start_date, datetime.min.time())
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())

    activities = []
    if athlete_id:
        activities = Activity.query.filter(
            Activity.athlete_id == athlete_id,
            Activity.date >= start_dt,
            Activity.date < end_dt,
        ).order_by(Activity.date.asc()).all()
    daily_metric_rows = []
    if athlete_id:
        daily_metric_rows = DailyMetric.query.filter(
            DailyMetric.athlete_id == athlete_id,
            DailyMetric.metric_date >= load_start_date,
            DailyMetric.metric_date <= end_date,
        ).order_by(DailyMetric.metric_date.asc()).all()

    intensity_minutes = {'low': 0.0, 'moderate': 0.0, 'high': 0.0}
    type_summary = {
        activity_type: {'sessions': 0, 'distance': 0.0, 'minutes': 0.0, 'tss': 0.0}
        for activity_type in ALL_ACTIVITY_TYPES
    }
    zone_minutes = {f'z{zone}': 0.0 for zone in range(1, 6)}
    daily = {}
    total_distance = 0.0
    total_minutes = 0.0
    total_elevation = 0.0
    total_calories = 0
    total_load = 0.0
    best_running_pace = None
    best_cycling_speed = None
    longest_activity = None

    for activity in activities:
        activity_type = activity.activity_type
        duration_minutes = (activity.duration_seconds or 0) / 60.0
        distance = activity.distance_km or 0.0
        intensity = activity.intensity if activity.intensity in intensity_minutes else 'moderate'
        activity_day = activity.date.date()
        tss = _estimate_activity_tss(activity)
        is_visible = activity_day >= start_date

        if is_visible:
            total_distance += distance
            total_minutes += duration_minutes
            total_elevation += activity.elevation_gain_m or 0
            total_calories += activity.calories_burned or 0
            total_load += tss
            intensity_minutes[intensity] += duration_minutes
        for zone in range(1, 6):
            if is_visible:
                zone_minutes[f'z{zone}'] += (getattr(activity, f'timez{zone}_seconds', 0) or 0) / 60.0

        if is_visible and activity_type in type_summary:
            type_summary[activity_type]['sessions'] += 1
            type_summary[activity_type]['distance'] += distance
            type_summary[activity_type]['minutes'] += duration_minutes
            type_summary[activity_type]['tss'] += tss

        day_key = activity_day.isoformat()
        if day_key not in daily:
            daily[day_key] = {'sessions': 0, 'distance': 0.0, 'minutes': 0.0, 'tss': 0.0}
        daily[day_key]['sessions'] += 1
        daily[day_key]['distance'] += distance
        daily[day_key]['minutes'] += duration_minutes
        daily[day_key]['tss'] += tss

        if is_visible and activity_type == 'running' and getattr(activity, 'pace_min_km', None) and activity.pace_min_km > 0:
            best_running_pace = min(best_running_pace or activity.pace_min_km, activity.pace_min_km)
        if is_visible and activity_type == 'cycling' and getattr(activity, 'speed_km_h', None) and activity.speed_km_h > 0:
            best_cycling_speed = max(best_cycling_speed or activity.speed_km_h, activity.speed_km_h)
        if is_visible and (longest_activity is None or distance > longest_activity['distance']):
            longest_activity = {'title': activity.title, 'type': activity_type, 'distance': distance, 'date': activity.date.date().isoformat()}

    daily_series = []
    ctl = 0.0
    atl = 0.0
    day = load_start_date
    while day <= end_date:
        values = daily.get(day.isoformat(), {'sessions': 0, 'distance': 0.0, 'minutes': 0.0, 'tss': 0.0})
        ctl = _ewma(ctl, values['tss'], 42)
        atl = _ewma(atl, values['tss'], 7)
        daily_series.append({**values, 'date': day.isoformat(), 'ctl': ctl, 'atl': atl, 'form': ctl - atl})
        day += timedelta(days=1)

    visible_days = [item for item in daily_series if item['date'] >= start_date.isoformat()]
    weeks = []
    week_start = start_date
    while week_start <= end_date:
        week_end = min(week_start + timedelta(days=6), end_date)
        week_days = [item for item in visible_days if week_start.isoformat() <= item['date'] <= week_end.isoformat()]
        week_metric_rows = [metric for metric in daily_metric_rows if week_start <= metric.metric_date <= week_end]
        def metric_average(field):
            values = [getattr(metric, field) for metric in week_metric_rows if getattr(metric, field) is not None]
            return round(sum(values) / len(values), 1) if values else None
        weeks.append({
            'label': week_start.strftime('%b %-d') if os.name != 'nt' else week_start.strftime('%b %#d'),
            'start': week_start.isoformat(),
            'sessions': sum(item['sessions'] for item in week_days),
            'distance': round(sum(item['distance'] for item in week_days), 1),
            'minutes': round(sum(item['minutes'] for item in week_days), 1),
            'tss': round(sum(item['tss'] for item in week_days), 1),
            'ctl': round(week_days[-1]['ctl'], 1) if week_days else 0,
            'atl': round(week_days[-1]['atl'], 1) if week_days else 0,
            'form': round(week_days[-1]['form'], 1) if week_days else 0,
            'sleep_hours': round((metric_average('sleep_duration_minutes') or 0) / 60.0, 2) if metric_average('sleep_duration_minutes') is not None else None,
            'resting_hr': metric_average('resting_hr'),
            'hrv_ms': metric_average('hrv_ms'),
            'readiness': metric_average('readiness_score'),
        })
        week_start += timedelta(days=7)

    active_days = len({activity.date.date() for activity in activities if activity.date.date() >= start_date})
    visible_sessions = sum(1 for activity in activities if activity.date.date() >= start_date)
    final_load = visible_days[-1] if visible_days else {'ctl': 0, 'atl': 0, 'form': 0}
    current_phase = TrainingPhase.query.join(TrainingSeason).filter(
        TrainingSeason.athlete_id == athlete_id,
        TrainingPhase.start_date <= end_date,
        TrainingPhase.end_date >= end_date,
    ).order_by(TrainingPhase.start_date.desc()).first() if athlete_id else None
    recovery_status = recovery_assessment(athlete_id, end_date) if athlete_id else {
        'status': 'missing', 'alerts': [], 'recent': {}, 'baseline': {}
    }
    weekly_tss = [week['tss'] for week in weeks]
    average_weekly_tss = sum(weekly_tss) / len(weekly_tss) if weekly_tss else 0
    tss_variance = sum((value - average_weekly_tss) ** 2 for value in weekly_tss) / len(weekly_tss) if weekly_tss else 0
    monotony = (average_weekly_tss / (tss_variance ** 0.5)) if tss_variance > 0 else 0
    return jsonify({
        'range_days': range_days,
        'from': start_date.isoformat(),
        'to': end_date.isoformat(),
        'summary': {
            'sessions': visible_sessions,
            'active_days': active_days,
            'consistency': round((active_days / range_days) * 100, 1),
            'distance': round(total_distance, 1),
            'minutes': round(total_minutes, 1),
            'elevation': round(total_elevation),
            'calories': total_calories,
            'load': round(total_load, 1),
            'tss': round(total_load, 1),
            'ctl': round(final_load['ctl'], 1),
            'atl': round(final_load['atl'], 1),
            'form': round(final_load['form'], 1),
            'monotony': round(monotony, 2),
            'strain': round(average_weekly_tss * monotony, 1),
        },
        'weekly': weeks,
        'intensity': [{'label': label.capitalize(), 'minutes': round(minutes, 1)} for label, minutes in intensity_minutes.items()],
        'zones': [{'label': label.upper(), 'minutes': round(minutes, 1)} for label, minutes in zone_minutes.items()],
        'types': [
            {'type': activity_type, 'sessions': values['sessions'], 'distance': round(values['distance'], 1), 'minutes': round(values['minutes'], 1), 'tss': round(values['tss'], 1)}
            for activity_type, values in type_summary.items()
        ],
        'records': {
            'longest': longest_activity,
            'best_running_pace': round(best_running_pace, 2) if best_running_pace is not None else None,
            'best_cycling_speed': round(best_cycling_speed, 1) if best_cycling_speed is not None else None,
        },
        'current_phase': {
            'name': current_phase.name,
            'type': current_phase.phase_type,
            'start_date': current_phase.start_date.isoformat(),
            'end_date': current_phase.end_date.isoformat(),
            'color': current_phase.color,
        } if current_phase else None,
        'recovery': recovery_status,
    })


@main.route('/activity/<int:activity_id>')
def activity_detail(activity_id):
    a = Activity.query.get(activity_id)
    if not a or not athlete_is_visible(a.athlete):
        abort(404)
    return render_template('activity.html', activity=a)


@main.route('/activity/<int:activity_id>/delete', methods=['POST'])
def delete_activity(activity_id):
    activity = Activity.query.get_or_404(activity_id)
    if not athlete_is_visible(activity.athlete):
        abort(404)
    db.session.delete(activity)
    db.session.commit()
    flash('Activity deleted.', 'success')
    return redirect(url_for('main.calendar'))

