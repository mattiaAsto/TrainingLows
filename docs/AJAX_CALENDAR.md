AJAX Calendar API for TrainingLows

This document explains the API endpoints added to `app/main/routes.py` for dynamic calendar rendering, the JSON shapes they return, and example client-side usage (already wired in `calendar.html`).

Endpoints

1) GET /api/calendar/week
- Params:
  - `start` (optional): ISO date string (YYYY-MM-DD or full ISO). The server will compute the week containing this date; week starts on Sunday.
- Response:
  {
    "week_days": [
      {"name":"Sunday","date":"2026-05-10","is_today":false,"workouts":[{...}]},
      ... (7 items)
    ],
    "prev_week": "2026-05-03",
    "next_week": "2026-05-17"
  }
- Each workout item: `{id, type, title, distance, time, date}`

2) GET /api/calendar/month
- Params:
  - `year` (optional)
  - `month` (optional)
- Response:
  {
    "calendar_month_weeks": [
      [ {"date":"2026-05-02","in_month":true,"activities":[{...}]}, ... 7 days ],
      ...
    ],
    "year": 2026,
    "month": 5,
    "prev_month": {"year":2026,"month":4},
    "next_month": {"year":2026,"month":6}
  }

3) GET /api/calendar/year
- Params: `year` (optional)
- Response: `{ "year":2026, "months": [{"name":"Jan","distance":123.4,"activity_count":12}, ...] }`

Client-side usage

- `calendar.html` already contains JS helpers that call these endpoints and render the returned JSON into the DOM (`fetchWeek`, `fetchMonth`, `fetchYear`). Study those functions for simple rendering logic.
- To fetch a specific month: `fetch('/api/calendar/month?year=2026&month=6').then(r=>r.json()).then(renderMonth)`
- To fetch a week containing a specific date: `fetch('/api/calendar/week?start=2026-06-01')`

Notes & tips

- Security: endpoints return activities filtered by the current authenticated athlete (if any). Ensure your view respects permissions.
- Date formats: server uses ISO date strings. On the client, create `new Date(dateString)` to parse.
- Performance: API endpoints perform a narrow query for the requested range; avoid calling the month endpoint for long ranges. Consider paginating or lazy-loading month details.

If you want, I can:
- Add server-side caching for these endpoints.
- Implement AJAX-based lazy-loading of details when expanding a day.
- Provide a small test script that calls the endpoints with sample dates.
