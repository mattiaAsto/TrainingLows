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

def get_current_week_activities(): #returns the list .reverse() -ed

    tomorrow = date.today() + timedelta(days=1) #query until tomorrow becaus the request is exclusive 
    start_weekday = tomorrow - timedelta(days=tomorrow.weekday())

    activities = Activity.query.filter(
        Activity.date >= start_weekday,
        Activity.date < tomorrow + timedelta(days=1)
        ).all()
    
    activities = activities[::-1] #reversing the list so it shows latest first in the homepage

    return activities

def create_current_week_stats_from_activities(activities):
    total_distance = 0
    total_elev = 0
    total_cal = 0
    total_time_s = 0

    for activity in activities:
        total_distance += activity.distance_km if activity.distance_km else 0
        total_elev += activity.elevation_gain_m if activity.elevation_gain_m  else 0
        total_cal += activity.calories_burned if activity.calories_burned else 0
        total_time_s += activity.duration_seconds
        
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

    

    return jsonify()




@main.context_processor
def global_injection_dictionary():

    return {
        "user": current_user,
    }


@main.route("/")
def home():

    week_activities = get_current_week_activities()


    return render_template("home.html", 
                           recent_activities = week_activities, 
                           this_week = create_current_week_stats_from_activities(week_activities)
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
    return render_template("graphs.html")


@main.route("/analysis")
def analysis():
    return render_template("analysis.html")


@main.route('/activity/<int:activity_id>')
def activity_detail(activity_id):
    a = Activity.query.get(activity_id)
    if not a:
        abort(404)
    return render_template('activity.html', activity=a)

