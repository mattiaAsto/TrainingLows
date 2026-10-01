import hmac
import json
import re
from datetime import datetime, timedelta, timezone

from flask import current_app, render_template, redirect, url_for, request, session, flash, abort, jsonify
from flask_login import current_user
from . import strava
from app import csrf, db
from app.models import get_activity_model
from app.models import *
from app.activity_catalog import ACTIVITY_COLORS
from app.rate_limit import enforce_rate_limit
from app.strava.auth import build_authorization_url, consume_oauth_state, exchange_code, get_valid_token
from app.strava import client as strava_client


STRAVA_TYPE_MAP = {
    'Run': Running,
    'VirtualRun': Running,
    'Ride': Cycling,
    'VirtualRide': Cycling,
    'Swim': Swimming,
    'WeightTraining': Strenght,
    'Workout': Strenght,
    'Walk': get_activity_model('walking'),
    'Hike': get_activity_model('hiking'),
    'Row': get_activity_model('rowing'),
    'AlpineSki': get_activity_model('skiing'),
    'NordicSki': get_activity_model('skiing'),
    'RockClimbing': get_activity_model('climbing'),
    'Yoga': get_activity_model('yoga'),
}


def _parse_strava_date(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _sanitize_text(value, max_length):
    """Strip markup from third-party text so it can never be rendered as HTML."""
    cleaned = re.sub(r'[<>`]', '', str(value or ''))
    return cleaned[:max_length].strip()


def _strava_activity_from_payload(payload, user_id, athlete_id):
    activity_type = payload.get('sport_type') or payload.get('type') or 'activity'
    return StravaActivity(
        user_id=user_id,
        athlete_id=athlete_id,
        external_id=int(payload['id']),
        status='pending',
        title=_sanitize_text(payload.get('name'), 160) or 'Strava activity',
        activity_type=activity_type,
        started_at=_parse_strava_date(payload.get('start_date') or payload.get('start_date_local')),
        duration_seconds=payload.get('moving_time') or payload.get('elapsed_time') or 0,
        distance_km=(payload.get('distance') or 0) / 1000.0,
        elevation_gain_m=payload.get('total_elevation_gain') or 0,
        calories_burned=round(payload['calories']) if payload.get('calories') is not None else None,
        average_speed_km_h=(payload.get('average_speed') or 0) * 3.6,
        average_heartrate=payload.get('average_heartrate'),
        raw_payload=json.dumps(payload),
    )


def _sync_strava_activities(user):
    StravaActivity.query.filter(
        StravaActivity.user_id == user.id,
        StravaActivity.status == 'rejected',
        StravaActivity.rejected_until < datetime.utcnow(),
    ).delete(synchronize_session=False)
    token = _get_strava_token_for_user(user)
    if token is None:
        raise LookupError('Connect Strava before refreshing activities.')
    latest = StravaActivity.query.filter_by(user_id=user.id).order_by(StravaActivity.started_at.desc()).first()
    after = int((latest.started_at - timedelta(minutes=1)).replace(tzinfo=timezone.utc).timestamp()) if latest else None
    payloads = strava_client.get_activities(token.athlete_id, per_page=200, after=after)
    created = 0
    imported = 0
    for payload in payloads:
        external_id = int(payload['id'])
        if StravaActivity.query.filter_by(user_id=user.id, external_id=external_id).first():
            continue
        item = _strava_activity_from_payload(payload, user.id, token.athlete_id)
        db.session.add(item)
        created += 1
        db.session.flush()
        if user.strava_auto_update:
            _import_strava_activity(item, user.athlete_profile)
            imported += 1
    db.session.commit()
    return created, imported


def sync_all_strava_users(app):
    """Fallback polling job for the six-hour background sync."""
    with app.app_context():
        for user in User.query.filter(User.strava_athlete_id.isnot(None)).all():
            try:
                _sync_strava_activities(user)
            except Exception:
                db.session.rollback()
                app.logger.exception('Scheduled Strava sync failed for user %s', user.id)


def _import_strava_activity(item, athlete):
    model_cls = STRAVA_TYPE_MAP.get(item.activity_type, Activity)
    activity = model_cls(
        athlete_id=athlete.id,
        title=_sanitize_text(item.title, 160) or 'Strava activity',
        activity_type='activity' if model_cls is Activity else model_cls.__mapper_args__['polymorphic_identity'],
        duration_seconds=item.duration_seconds or 0,
        distance_km=item.distance_km,
        calories_burned=item.calories_burned,
        elevation_gain_m=item.elevation_gain_m,
        intensity='moderate',
        description=f'Imported from Strava activity {int(item.external_id)}',
        date=item.started_at,
    )
    if isinstance(activity, Running):
        activity.pace_min_km = (item.duration_seconds / 60 / item.distance_km) if item.distance_km else None
    if isinstance(activity, Cycling):
        activity.speed_km_h = item.average_speed_km_h
    db.session.add(activity)
    item.status = 'imported'
    item.reviewed_at = datetime.utcnow()
    return activity


def _get_strava_token_for_user(user):
    """Return only the Strava token explicitly linked to this user."""
    from app.models import StravaToken

    athlete_id = getattr(user, "strava_athlete_id", None)
    if athlete_id is None:
        return None
    return StravaToken.query.filter_by(athlete_id=athlete_id).first()


def _get_current_strava_token():
    return _get_strava_token_for_user(current_user)


@strava.context_processor
def global_injection_dictionary():
    return {
        "user": current_user,
    }


# ── Connect / OAuth flow ───────────────────────────────────────────────────────

@strava.route("/connect")
def connect():
    """Redirect the athlete to Strava's OAuth consent page."""
    if not current_app.config.get('STRAVA_API_ACTIVE', False):
        flash('Strava integration is temporarily unavailable. Please try again later.', 'warning')
        return redirect(url_for('strava.settings'))
    return redirect(build_authorization_url())


@strava.route("/callback")
def callback():
    """
    Strava redirects here after the athlete grants or denies access.
    Exchanges the one-time code for access + refresh tokens.
    """
    if not current_app.config.get('STRAVA_API_ACTIVE', False):
        flash('Strava integration is temporarily unavailable.', 'warning')
        return redirect(url_for('strava.settings'))

    if not consume_oauth_state(request.args.get('state')):
        abort(400)

    error = request.args.get("error")
    if error:
        flash("Strava connection was denied. Please try again.", "danger")
        return redirect(url_for("strava.settings"))

    code = request.args.get("code")
    if not code:
        flash("Invalid callback — missing authorisation code.", "danger")
        return redirect(url_for("strava.settings"))

    try:
        token = exchange_code(code)
        # Always keep the user cache aligned with the real Strava token record.
        current_user.strava_athlete_id = token.athlete_id
        db.session.add(current_user)
        db.session.commit()
        db.session.refresh(current_user)

        # Verify the token immediately; a green popup should only appear if Strava accepts it.
        strava_client.get_athlete(token.athlete_id)
        flash("Strava account connected successfully!", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Strava OAuth callback failed for user %s', current_user.id)
        flash('Strava connection failed. Please try reconnecting later.', 'danger')

    return redirect(url_for("strava.settings"))


@strava.route("/disconnect", methods=['POST'])
def disconnect():
    """Remove the stored Strava token for the current athlete."""
    if not current_app.config.get('STRAVA_API_ACTIVE', False):
        flash('Strava integration is temporarily unavailable.', 'warning')
        return redirect(url_for('strava.settings'))
    from app.models import StravaToken

    token = _get_current_strava_token()
    if token:
        db.session.delete(token)
    if current_user.is_authenticated:
        current_user.strava_athlete_id = None
    db.session.commit()
    flash("Strava account disconnected.", "info")
    return redirect(url_for("strava.settings"))


@strava.route('/sync/refresh', methods=['POST'])
def refresh():
    if not current_app.config.get('STRAVA_API_ACTIVE', False):
        flash('Strava integration is temporarily unavailable.', 'warning')
        return redirect(url_for('strava.settings'))
    if not current_user.is_athlete or not current_user.athlete_profile:
        abort(403)
    try:
        created, imported = _sync_strava_activities(current_user)
        flash(f'Strava refresh complete: {created} new activities found, {imported} imported.', 'success')
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Strava refresh failed')
        flash('Strava refresh failed. Please try again later.', 'danger')
    return redirect(url_for('strava.settings'))


@strava.route('/sync/auto-update', methods=['POST'])
def set_auto_update():
    if not current_app.config.get('STRAVA_API_ACTIVE', False):
        flash('Strava integration is temporarily unavailable.', 'warning')
        return redirect(url_for('strava.settings'))
    if not current_user.is_athlete or not current_user.athlete_profile:
        abort(403)
    enabled = request.form.get('enabled') == '1'
    pending_count = StravaActivity.query.filter_by(user_id=current_user.id, status='pending').count()
    if enabled and pending_count and request.form.get('confirm_pending') != '1':
        return render_template('strava_auto_confirm.html', pending_count=pending_count)
    current_user.strava_auto_update = enabled
    db.session.commit()
    if enabled and request.form.get('import_pending') == '1':
        for item in StravaActivity.query.filter_by(user_id=current_user.id, status='pending').all():
            _import_strava_activity(item, current_user.athlete_profile)
        db.session.commit()
    flash('Automatic Strava updates enabled.' if enabled else 'Automatic Strava updates disabled.', 'success')
    return redirect(url_for('strava.settings'))


@strava.route('/activity/<int:item_id>/review', methods=['POST'])
def review_activity(item_id):
    if not current_app.config.get('STRAVA_API_ACTIVE', False):
        flash('Strava integration is temporarily unavailable.', 'warning')
        return redirect(url_for('strava.settings'))
    if not current_user.is_athlete or not current_user.athlete_profile:
        abort(403)
    item = StravaActivity.query.filter_by(id=item_id, user_id=current_user.id, status='pending').first_or_404()
    decision = request.form.get('decision')
    if decision == 'accept':
        _import_strava_activity(item, current_user.athlete_profile)
        flash('Strava activity imported.', 'success')
    elif decision == 'reject':
        item.status = 'rejected'
        item.reviewed_at = datetime.utcnow()
        item.rejected_until = datetime.utcnow() + timedelta(days=15)
        flash('Strava activity rejected and archived for 15 days.', 'info')
    else:
        abort(400)
    db.session.commit()
    return redirect(url_for('strava.settings'))


@strava.route('/webhook', methods=['GET', 'POST'])
@csrf.exempt
def webhook():
    if not current_app.config.get('STRAVA_API_ACTIVE', False):
        return jsonify({'error': 'Strava integration unavailable'}), 503
    if request.method == 'GET':
        verify_token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        expected_token = current_app.config.get('STRAVA_WEBHOOK_VERIFY_TOKEN')
        token_matches = bool(verify_token and expected_token) and hmac.compare_digest(verify_token, expected_token)
        if token_matches and challenge:
            return jsonify({'hub.challenge': challenge})
        return jsonify({'error': 'Invalid verify token'}), 403

    payload = request.get_json(silent=True) or {}
    if payload.get('object_type') != 'activity' or payload.get('aspect_type') not in ('create', 'update'):
        return jsonify({'status': 'ignored'})
    enforce_rate_limit('strava-webhook', 120, 60)
    try:
        owner_id = int(payload.get('owner_id'))
        object_id = int(payload.get('object_id'))
    except (TypeError, ValueError):
        return jsonify({'status': 'ignored'})
    user = User.query.filter_by(strava_athlete_id=owner_id).first()
    if user is None:
        return jsonify({'status': 'unmatched'}), 202
    try:
        activity = strava_client.get_activity(owner_id, object_id)
        # Never import an activity that does not belong to the webhook's owner:
        # otherwise forged events could smuggle any readable activity into a
        # victim's inbox or, with auto-update on, straight into their log.
        activity_athlete_id = (activity.get('athlete') or {}).get('id')
        if activity_athlete_id != owner_id:
            current_app.logger.warning(
                'Strava webhook owner mismatch: event owner=%s activity athlete=%s',
                owner_id, activity_athlete_id,
            )
            return jsonify({'status': 'ignored'})
        if not StravaActivity.query.filter_by(user_id=user.id, external_id=object_id).first():
            item = _strava_activity_from_payload(activity, user.id, owner_id)
            db.session.add(item)
            db.session.flush()
            if user.strava_auto_update and user.athlete_profile:
                _import_strava_activity(item, user.athlete_profile)
            db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Strava webhook processing failed')
        return jsonify({'error': 'Webhook processing failed'}), 500
    return jsonify({'status': 'accepted'}), 200


# ── Settings page (connect / status) ──────────────────────────────────────────

@strava.route("/settings")
def settings():
    """
    Page where the user connects or manages their Strava account.
    Passes `connected=True/False` and the athlete profile if connected.
    """
    api_active = current_app.config.get('STRAVA_API_ACTIVE', False)

    StravaActivity.query.filter(
        StravaActivity.user_id == current_user.id,
        StravaActivity.status == 'rejected',
        StravaActivity.rejected_until < datetime.utcnow(),
    ).delete(synchronize_session=False)
    db.session.commit()

    connected = False
    athlete = None

    token = _get_current_strava_token()
    if api_active and token is not None:
        try:
            athlete = strava_client.get_athlete(token.athlete_id)
            connected = True
        except Exception:
            # Token might be invalid — treat as disconnected.
            current_app.logger.warning('Could not validate the connected Strava token for user %s.', current_user.id)
            connected = False

    return render_template(
        "strava_settings.html",
        connected=connected,
        athlete=athlete,
        api_active=api_active,
        auto_update=current_user.strava_auto_update if current_user.is_authenticated else False,
        activity_colors=ACTIVITY_COLORS,
        pending_activities=StravaActivity.query.filter_by(user_id=current_user.id, status='pending').order_by(StravaActivity.started_at.desc()).all() if current_user.is_authenticated else [],
    )