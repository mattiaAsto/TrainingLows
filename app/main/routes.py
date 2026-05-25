from flask import render_template, request, redirect, url_for, session, flash, jsonify, abort
from . import main
from app.models import *
from app import db, cache
from werkzeug.security import check_password_hash
from flask_login import login_manager, current_user, login_user, logout_user
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo
from sqlalchemy import distinct, create_engine, text
from app.strava.client import *
import os
import json
import time
import random
import bcrypt
import calendar as _calendar


ALL_ACTIVITY_TYPES = Activity.get_activity_types()


def get_week_activities(date_start: datetime, date_stop: datetime, activity_type = "all"): #returns the list .reverse() -ed

    if activity_type == "all":
        activities = Activity.query.filter(
            Activity.date >= date_start,
            Activity.date < date_stop + timedelta(days=1)
            ).all()
    
    else:
        activities = Activity.query.filter(
            Activity.date >= date_start,
            Activity.date < date_stop + timedelta(days=1),
            Activity.activity_type == activity_type,
            ).all()
    
    return activities

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
    }


@main.route("/")
def home():

    today = date.today() #query until tomorrow becaus the request is exclusive 
    start_weekday = today - timedelta(days=today.weekday())

    week_activities = get_week_activities(start_weekday, today)
    week_activities = week_activities[::-1]

    return render_template("home.html", 
                           recent_activities = week_activities, 
                           this_week = create_week_stats_from_activities(week_activities)
                           )


@main.route("/calendar")
def calendar():
    # initial render can be server-side, but client will fetch dynamic data via AJAX
    return render_template("calendar.html")


def _activity_to_dict(a):
    return {
        'id': a.id,
        'type': a.activity_type,
        'title': getattr(a, 'description', None) or a.activity_type,
        'distance': getattr(a, 'distance_km', None) or 0,
        'time': a.get_duration_formatted() if hasattr(a, 'get_duration_formatted') else None,
        'date': a.date.isoformat() if hasattr(a, 'date') else None
    }

def get_current_athlete_id():
    try:
        if current_user.is_authenticated and current_user.is_athlete:
            return current_user.athlete_profile.id
    except Exception:
        pass
    return None


def activity_query(start_dt, end_dt, activity_type=None):
    q = Activity.query
    athlete_id = get_current_athlete_id()
    if athlete_id:
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
    athlete_id = None
    try:
        if current_user.is_authenticated and current_user.is_athlete:
            athlete_id = current_user.athlete_profile.id
    except Exception:
        athlete_id = None

    # load activities in range
    start_dt = datetime.combine(monday, datetime.min.time())
    end_dt = datetime.combine(monday + timedelta(days=6), datetime.max.time())
    activities = []
    if athlete_id:
        activities = Activity.query.filter(Activity.athlete_id==athlete_id, Activity.date >= start_dt, Activity.date <= end_dt).all()

    for i in range(7):
        d = monday + timedelta(days=i)
        day_acts = []
        for a in activities:
            if a.date.date() == d:
                day_acts.append(_activity_to_dict(a))
        week_days.append({
            'name': d.strftime('%A'),
            'date': d.isoformat(),
            'is_today': d == date.today(),
            'workouts': day_acts
        })

    # navigation helpers
    prev_week = (monday - timedelta(days=7)).isoformat()
    next_week = (monday + timedelta(days=7)).isoformat()

    return jsonify({'week_days': week_days, 'prev_week': prev_week, 'next_week': next_week})


@main.route('/api/graphs/activity_distribution')
def api_graphs_activity_distribution():
    view = request.args.get('view', 'week').lower()
    start_dt, end_dt = _timespan_bounds(view)
    activities = activity_query(start_dt, end_dt).all()

    totals = {tp: 0.0 for tp in ALL_ACTIVITY_TYPES if tp != 'strength'}
    for activity in activities:
        if activity.activity_type in totals:
            totals[activity.activity_type] += getattr(activity, 'distance_km', 0) or 0

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

    calories = {tp: 0 for tp in ALL_ACTIVITY_TYPES if tp != 'strength'}
    for activity in activities:
        if activity.activity_type in calories:
            calories[activity.activity_type] += getattr(activity, 'calories_burned', 0) or 0

    labels = [tp.capitalize() for tp in calories.keys()]
    values = [calories[tp] for tp in calories.keys()]

    return jsonify({'view': view, 'labels': labels, 'values': values})


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
    athlete_id = None
    try:
        if current_user.is_authenticated and current_user.is_athlete:
            athlete_id = current_user.athlete_profile.id
    except Exception:
        athlete_id = None

    # build weeks
    activities = []
    if athlete_id:
        start_dt = datetime.combine(first_day - timedelta(days=7), datetime.min.time())
        end_dt = datetime.combine(first_day + timedelta(days=40), datetime.max.time())
        activities = Activity.query.filter(Activity.athlete_id==athlete_id, Activity.date >= start_dt, Activity.date <= end_dt).all()

    week = []
    for d in cal.itermonthdates(year, month):
        day_acts = []
        for a in activities:
            if a.date.date() == d:
                day_acts.append(_activity_to_dict(a))
        day = {
            'date': d.isoformat(),
            'in_month': (d.month == month),
            'activities': day_acts
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

    athlete_id = None
    try:
        if current_user.is_authenticated and current_user.is_athlete:
            athlete_id = current_user.athlete_profile.id
    except Exception:
        athlete_id = None

    months = []
    for m in range(1,13):
        # aggregate simple sums
        total_distance = 0
        elevation_gain = 0
        count = 0
        if athlete_id:
            start_dt = datetime(year, m, 1)
            # naive end day
            end_dt = (start_dt.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            acts = Activity.query.filter(Activity.athlete_id==athlete_id, Activity.date >= start_dt, Activity.date <= end_dt).all()
            for a in acts:
                total_distance += getattr(a, 'distance_km', 0) or 0
                elevation_gain += getattr(a, 'elevation_gain_m', 0) or 0
            count = len(acts)
        months.append({'name': datetime(year, m, 1).strftime('%b'), 'distance': total_distance, 'activity_count': count, 'elevation': elevation_gain})

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
        if activity_type == 'strength': continue
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
        if activity_type == 'strength': continue
        row = { 'activitytype': activity_type, 'labels': [], 'distances': [] }
        for d in range(1, ndays+1):
            start_dt = datetime(year, month, d)
            acts = get_week_activities(start_dt, start_dt, activity_type)
            s = 0
            for a in acts:
                s += getattr(a, 'distance_km', 0) or 0
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
        if activity_type == 'strength': continue
        row = { 'activitytype': activity_type, 'labels': [], 'distances': [] }
        for m in range(1,13):
            start_dt = datetime(year, m, 1)
            # naive end of month
            end_dt = (start_dt.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            acts = get_week_activities(start_dt, end_dt, activity_type)
            s = 0
            for a in acts:
                s += getattr(a, 'distance_km', 0) or 0
            row['labels'].append(start_dt.strftime('%b'))
            row['distances'].append(round(s,1))
        result.append(row)
    return jsonify({'year': year, 'data': result})


@main.route("/analysis")
def analysis():
    return render_template("analysis.html")


@main.route('/activity/<int:activity_id>')
def activity_detail(activity_id):
    a = Activity.query.get(activity_id)
    if not a:
        abort(404)
    return render_template('activity.html', activity=a)

