Calendar Data Integration for TrainingLows

Overview
- This document explains the expected data structures and how to populate the calendar templates (`calendar.html`) from Flask views.

Key template variables
- `week_days`: list of 7 day objects for the week view. Each day object should have:
  - `name`: weekday name (e.g., 'Monday')
  - `date`: a date object (use `.day` in template for day number)
  - `is_today`: boolean
  - `workouts`: list of workout dicts with keys: `type` ('running'|'cycling'|'swimming'), `title`, `distance`, `time`

- `calendar_month_weeks`: list of weeks (each week is list of 7 day objects). Each day object should have:
  - `date`: date object
  - `in_month`: boolean (true if the day belongs to the currently-viewed month)
  - `activities`: list of activity dicts with keys: `activity_type`, `title`, `type` (for coloring), etc.

- `year_months`: list of month summaries for year view. Each month item: `name`, `distance`, `activity_count`.

- Navigation helpers (optional but useful): `prev_week`, `next_week`, `prev_month`, `next_month`, `prev_year`, `next_year` — simple identifiers or strings your view can interpret when building navigation URLs.

How to build these structures in Flask
- Week view example (Python):

```py
from datetime import date, timedelta

def build_week(reference_date):
    # reference_date: a date object (e.g., today or the week start)
    week_days = []
    start = reference_date - timedelta(days=reference_date.weekday()+1) if reference_date.weekday()<6 else reference_date
    # simpler: choose your week start logic
    for i in range(7):
        d = start + timedelta(days=i)
        day = {
            'name': d.strftime('%A'),
            'date': d,
            'is_today': (d == date.today()),
            'workouts': []  # populate from DB by filtering on date
        }
        week_days.append(day)
    return week_days
```

- Month view example (Python):

```py
import calendar

def build_month(year, month):
    cal = calendar.Calendar()
    month_weeks = []
    week = []
    for d in cal.itermonthdates(year, month):
        day = {
            'date': d,
            'in_month': (d.month == month),
            'activities': []  # populate from DB
        }
        week.append(day)
        if len(week) == 7:
            month_weeks.append(week)
            week = []
    return month_weeks
```

Filling activities from the DB
- Query your Activity model for the date range shown (week or month) and attach activities to the matching day object. Example:

```py
activities = Activity.query.filter(Activity.athlete_id==user.id, Activity.date >= start_date, Activity.date <= end_date).all()
for a in activities:
    # find matching day object and append
    # convert ORM object to dict with keys expected in template
    obj = {'type': a.activity_type, 'title': a.title or a.activity_type, 'distance': a.distance_km, 'time': a.get_duration_formatted()}
    # attach to day.workouts or day.activities depending on view

```

Performance tips
- Only build data for the current month when rendering month view; avoid loading multi-year datasets on page load.
- Use aggregated counts and prefetching when possible.
- Consider AJAX endpoints for lazy-loading month details.

Template notes
- `calendar.html` includes fallbacks with sample data when no variables are provided; for production use, pass real data from your views.
- Colors follow `type` values: `running` -> red, `cycling` -> blue, `swimming` -> green. Ensure your activity dict has `type` or `activity_type` accordingly.

If you want, I can implement example view functions in `app/main/routes.py` to return these structures and wire the templates. 
