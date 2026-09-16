from datetime import date, datetime, timedelta
from flask import abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_mail import Message
from flask_login import current_user

from app import db, mail
from app.activity_catalog import ACTIVITY_COLORS
from app.athlete_context import athlete_is_visible, managed_athletes as get_roster_for_current_user, selected_athlete as get_selected_athlete
from app.models import Activity, Athlete, Coach, PendingInvite, PlannedActivity, StravaActivity, User
from . import settings


ATHLETE_STATES = {
    'ready': 'Ready to train',
    'normal': 'Feeling normal',
    'fatigued': 'Fatigued',
    'rest': 'Need extra rest',
    'sick': 'Sick',
    'injured': 'Injured',
}


def _decode_invite_token(token, salt_name='settings-link-token'):
    if not token:
        return None
    try:
        return current_app.url_serializer.loads(token, salt=salt_name, max_age=60 * 60 * 24 * 30)
    except Exception:
        return None


def _encode_invite_token(payload, salt_name='settings-link-token'):
    return current_app.url_serializer.dumps(payload, salt=salt_name)


def _send_invitation_email(recipient, recipient_name, sender_name, invite_url, invitation_type):
    if not current_app.config.get('MAIL_SERVER') or not current_app.config.get('MAIL_DEFAULT_SENDER'):
        return False

    message = Message(
        subject=f'{sender_name} invited you to connect on TrainingLows',
        recipients=[recipient],
        sender=current_app.config.get('MAIL_DEFAULT_SENDER'),
        body=(
            f'Hi {recipient_name},\n\n'
            f'{sender_name} sent you a {invitation_type} invitation on TrainingLows.\n\n'
            f'Open the invitation here:\n{invite_url}\n\n'
            'You will need to sign in to review and accept or decline it.\n\n'
            'If you were not expecting this invitation, you can ignore this email.'
        ),
    )
    try:
        mail.send(message)
        return True
    except Exception:
        current_app.logger.exception('Could not send TrainingLows invitation email')
        return False


def _send_verification_email(user):
    token = current_app.url_serializer.dumps({'email': user.email}, salt='email-verification')
    verification_url = url_for('auth.verify_email_token', token=token, _external=True)

    if not current_app.config.get('MAIL_SERVER') or not current_app.config.get('MAIL_DEFAULT_SENDER'):
        flash(f'Verification link: {verification_url}', 'info')
        return True

    message = Message(
        subject='Verify your TrainingLows email address',
        recipients=[user.email],
        sender=current_app.config.get('MAIL_DEFAULT_SENDER'),
        body=(
            f'Hi {user.first_name},\n\n'
            f'Please verify your email address by opening this link:\n{verification_url}\n\n'
            'If you did not request this change, you can ignore this email.'
        ),
    )
    try:
        mail.send(message)
        return True
    except Exception:
        current_app.logger.exception('Could not send TrainingLows verification email')
        return False


def _ensure_role_flags(user):
    if user is None:
        return
    if user.athlete_profile is not None:
        user.is_athlete = True
    if user.coach_profile is not None:
        user.is_trainer = True


def _ensure_athlete_profile_for_user(user):
    if user is None:
        return None
    if user.athlete_profile is None:
        athlete_profile = Athlete(id=user.id, sport='running', date_of_birth=None)
        db.session.add(athlete_profile)
        user.is_athlete = True
        db.session.flush()
        return athlete_profile
    return user.athlete_profile


def _ensure_trainer_profile_for_user(user):
    if user is None:
        return None
    if user.coach_profile is None:
        coach_profile = Coach(id=user.id, specialization='General', bio='Linked via invite flow')
        db.session.add(coach_profile)
        user.is_trainer = True
        db.session.flush()
        return coach_profile
    return user.coach_profile


def get_pending_invites_for_current_user():
    if not current_user.is_authenticated:
        return []
    return PendingInvite.query.filter(
        PendingInvite.to_user_id == current_user.id,
        PendingInvite.status == 'pending',
    ).order_by(PendingInvite.created_at.desc()).all()


def get_pending_strava_for_current_user():
    if not current_user.is_authenticated or not current_user.is_athlete:
        return []
    return StravaActivity.query.filter_by(user_id=current_user.id, status='pending').order_by(StravaActivity.started_at.desc()).limit(5).all()


def get_trainer_link_context(athlete):
    if athlete is None:
        return [], []
    linked_trainers = list(athlete.coaches)
    pending_invites = PendingInvite.query.filter_by(
        from_user_id=athlete.user.id,
        kind='trainer_link',
        status='pending',
    ).order_by(PendingInvite.created_at.desc()).all()
    return linked_trainers, pending_invites


def get_athlete_overview_context(athlete):
    recent_activities = Activity.query.filter_by(athlete_id=athlete.id).order_by(Activity.date.desc()).limit(8).all()
    planned_activities = PlannedActivity.query.filter_by(athlete_id=athlete.id).order_by(PlannedActivity.planned_date.asc()).limit(10).all()
    stats = {
        'total_distance': round(sum((item.distance_km or 0) for item in recent_activities), 1),
        'total_sessions': len(recent_activities),
        'total_minutes': round(sum((item.duration_seconds or 0) / 60 for item in recent_activities), 0),
    }
    return {
        'recent_activities': recent_activities,
        'planned_activities': planned_activities,
        'stats': stats,
    }


@settings.context_processor
def inject_settings_context():
    return {
        'user': current_user,
        'selected_athlete': get_selected_athlete(),
        'available_athletes': get_roster_for_current_user(),
        'pending_invites': get_pending_invites_for_current_user(),
        'pending_strava_activities': get_pending_strava_for_current_user(),
        'activity_colors': ACTIVITY_COLORS,
    }


@settings.route('/')
def settings_home():
    if current_user.is_trainer:
        _ensure_trainer_profile_for_user(current_user)
        db.session.commit()
    athlete = get_selected_athlete()
    pending_invites = get_pending_invites_for_current_user()
    pending_strava_activities = get_pending_strava_for_current_user()
    linked_trainers, outgoing_trainer_invites = get_trainer_link_context(current_user.athlete_profile)

    return render_template(
        'account_settings.html',
        athlete=athlete,
        pending_invites=pending_invites,
        pending_strava_activities=pending_strava_activities,
        linked_trainers=linked_trainers,
        outgoing_trainer_invites=outgoing_trainer_invites,
    )


@settings.route('/roster')
def roster():
    if current_user.is_trainer and current_user.coach_profile is None:
        _ensure_trainer_profile_for_user(current_user)
        db.session.commit()
    return render_template(
        'roster.html',
        athlete=get_selected_athlete(),
        roster=get_roster_for_current_user(),
        pending_invites=get_pending_invites_for_current_user(),
        linked_trainers=list(current_user.athlete_profile.coaches) if current_user.athlete_profile else [],
        outgoing_trainer_invites=get_trainer_link_context(current_user.athlete_profile)[1],
        athlete_states=ATHLETE_STATES,
    )


@settings.route('/athlete/state', methods=['POST'])
def update_athlete_state():
    if not current_user.is_athlete:
        abort(403)
    athlete = _ensure_athlete_profile_for_user(current_user)
    state = (request.form.get('state') or '').strip().lower()
    if state not in ATHLETE_STATES:
        flash('Please choose a valid training state.', 'warning')
        return redirect(url_for('settings.roster'))
    athlete.self_reported_state = state
    athlete.self_reported_note = (request.form.get('note') or '').strip()[:500] or None
    athlete.self_reported_at = datetime.now()
    db.session.commit()
    flash('Your training state was updated.', 'success')
    return redirect(url_for('settings.roster'))


@settings.route('/profile/update', methods=['POST'])
def update_profile():
    first_name = (request.form.get('first_name') or '').strip()
    last_name = (request.form.get('last_name') or '').strip()
    email = (request.form.get('email') or '').strip().lower()

    if not first_name or not last_name or not email:
        flash('First name, last name, and email are required.', 'warning')
        return redirect(url_for('settings.settings_home'))

    existing_user = User.query.filter(User.email == email, User.id != current_user.id).first()
    if existing_user:
        flash('That email address is already in use.', 'warning')
        return redirect(url_for('settings.settings_home'))

    email_changed = email != current_user.email.lower()
    current_user.first_name = first_name
    current_user.last_name = last_name
    current_user.email = email
    current_user.activity_tint_enabled = request.form.get('activity_tint_enabled') == 'on'

    athlete_profile = current_user.athlete_profile
    if athlete_profile is not None:
        athlete_profile.sport = (request.form.get('sport') or '').strip() or athlete_profile.sport
        birth_date = (request.form.get('date_of_birth') or '').strip()
        if birth_date:
            try:
                athlete_profile.date_of_birth = datetime.strptime(birth_date, '%Y-%m-%d').date()
            except ValueError:
                flash('Please provide a valid date of birth.', 'warning')
                return redirect(url_for('settings.settings_home'))

    if email_changed:
        current_user.verified_email = False
    db.session.commit()

    if email_changed:
        sent = _send_verification_email(current_user)
        flash(
            'Your email was changed. Verify the new address to restore full account access.' if sent
            else 'Your email was changed, but the verification email could not be sent.',
            'warning',
        )
    else:
        flash('Personal data updated.', 'success')
    return redirect(url_for('settings.settings_home'))


@settings.route('/profile/send-verification', methods=['POST'])
def send_verification():
    if current_user.verified_email:
        flash('Your email address is already verified.', 'info')
        return redirect(url_for('settings.settings_home'))

    _send_verification_email(current_user)
    flash('A new verification email has been sent.', 'success')
    return redirect(url_for('settings.settings_home'))


@settings.route('/athlete/select/<int:athlete_id>')
def switch_athlete(athlete_id):
    athlete = Athlete.query.get_or_404(athlete_id)
    if not athlete_is_visible(athlete):
        abort(403)

    session['selected_athlete_id'] = athlete.id
    flash(f'Now managing {athlete.user.first_name} {athlete.user.last_name}.', 'success')
    destination = {
        'calendar': 'main.calendar',
        'graphs': 'main.graphs',
        'analysis': 'main.analysis',
        'planning': 'season.season_home',
        'session': 'planner.add_entry',
    }.get(request.args.get('next'))
    if destination:
        return redirect(url_for(destination))
    return redirect(url_for('settings.settings_home'))


@settings.route('/invite/trainer', methods=['POST'])
def invite_trainer():
    if not current_user.is_athlete:
        abort(403)
    athlete_profile = _ensure_athlete_profile_for_user(current_user)
    db.session.commit()

    trainer_email = (request.form.get('trainer_email', '') or '').strip().lower()
    if not trainer_email:
        flash('Please enter the trainer email.', 'warning')
        return redirect(url_for('settings.roster'))

    trainer = User.query.filter_by(email=trainer_email).first()
    if trainer is None or (not trainer.is_trainer and trainer.coach_profile is None):
        flash('That account is not registered as a trainer yet.', 'warning')
        return redirect(url_for('settings.roster'))

    if trainer.id in {coach.id for coach in current_user.athlete_profile.coaches}:
        flash(f'{trainer.first_name} {trainer.last_name} is already linked as your trainer.', 'info')
        return redirect(url_for('settings.roster'))

    existing_invite = PendingInvite.query.filter_by(
        from_user_id=current_user.id,
        to_user_id=trainer.id,
        kind='trainer_link',
        status='pending',
    ).first()
    if existing_invite:
        flash(f'An invitation to {trainer.first_name} {trainer.last_name} is already pending.', 'info')
        return redirect(url_for('settings.roster'))

    payload = {
        'kind': 'trainer_link',
        'athlete_id': athlete_profile.id,
        'trainer_id': trainer.id,
    }
    token = _encode_invite_token(payload)
    invite_url = url_for('settings.confirm_trainer_link', token=token, _external=True)

    pending_invite = PendingInvite.query.filter_by(token=token).first()
    if pending_invite is None:
        pending_invite = PendingInvite(
            kind='trainer_link',
            from_user_id=current_user.id,
            to_user_id=trainer.id,
            token=token,
            status='pending',
        )
        db.session.add(pending_invite)
        db.session.commit()

    sent = _send_invitation_email(
        trainer.email,
        trainer.first_name,
        f'{current_user.first_name} {current_user.last_name}',
        invite_url,
        'trainer',
    )
    flash(
        f'Invitation email sent to {trainer.email}.' if sent else 'The invitation was created, but the email could not be sent. Check your mail configuration.',
        'success' if sent else 'warning',
    )
    return redirect(url_for('settings.roster'))


@settings.route('/invite/athlete', methods=['POST'])
def invite_athlete():
    if not current_user.is_trainer or current_user.coach_profile is None:
        if not current_user.is_trainer:
            abort(403)
        _ensure_trainer_profile_for_user(current_user)
        db.session.commit()

    athlete_email = (request.form.get('athlete_email', '') or '').strip().lower()
    birthdate_value = (request.form.get('date_of_birth', '') or '').strip()
    if not athlete_email:
        flash('Please enter the athlete email.', 'warning')
        return redirect(url_for('settings.roster'))
    if not birthdate_value:
        flash('The athlete birthdate is required to confirm the collaboration request.', 'warning')
        return redirect(url_for('settings.roster'))

    try:
        requested_birthdate = datetime.strptime(birthdate_value, '%Y-%m-%d').date()
    except ValueError:
        flash('Please provide a valid athlete birthdate.', 'warning')
        return redirect(url_for('settings.roster'))

    athlete_user = User.query.filter_by(email=athlete_email).first()
    if athlete_user is None or (not athlete_user.is_athlete and athlete_user.athlete_profile is None):
        flash('That account is not registered as an athlete yet.', 'warning')
        return redirect(url_for('settings.roster'))

    athlete_profile = athlete_user.athlete_profile
    if athlete_profile is None or athlete_profile.date_of_birth is None:
        flash('That athlete does not have a birthdate on their profile, so the invitation cannot be verified.', 'warning')
        return redirect(url_for('settings.roster'))
    if athlete_profile.date_of_birth != requested_birthdate:
        flash('The email and birthdate do not match the athlete profile. No invitation was sent.', 'warning')
        return redirect(url_for('settings.roster'))

    payload = {
        'kind': 'athlete_link',
        'coach_id': current_user.id,
        'athlete_id': athlete_user.id,
        'date_of_birth': requested_birthdate.isoformat() if requested_birthdate else None,
    }
    token = _encode_invite_token(payload)
    invite_url = url_for('settings.confirm_athlete_link', token=token, _external=True)

    pending_invite = PendingInvite.query.filter_by(token=token).first()
    if pending_invite is None:
        pending_invite = PendingInvite(
            kind='athlete_link',
            from_user_id=current_user.id,
            to_user_id=athlete_user.id,
            token=token,
            status='pending',
        )
        db.session.add(pending_invite)
        db.session.commit()

    sent = _send_invitation_email(
        athlete_user.email,
        athlete_user.first_name,
        f'{current_user.first_name} {current_user.last_name}',
        invite_url,
        'athlete',
    )
    flash(
        f'Invitation email sent to {athlete_user.email}.' if sent else 'The invitation was created, but the email could not be sent. Check your mail configuration.',
        'success' if sent else 'warning',
    )
    return redirect(url_for('settings.roster'))


@settings.route('/confirm/trainer/<token>', methods=['GET', 'POST'])
def confirm_trainer_link(token):
    payload = _decode_invite_token(token)
    if payload is None or payload.get('kind') != 'trainer_link':
        flash('This trainer link is invalid or expired.', 'warning')
        return redirect(url_for('settings.settings_home'))

    athlete = Athlete.query.get(payload.get('athlete_id'))
    trainer = User.query.get(payload.get('trainer_id'))
    if athlete is None or trainer is None:
        flash('This trainer link is no longer valid.', 'warning')
        return redirect(url_for('settings.settings_home'))

    if not current_user.is_authenticated:
        return redirect(url_for('auth.login'))
    if current_user.id != trainer.id:
        flash('This invitation is intended for the trainer account only.', 'warning')
        return redirect(url_for('settings.settings_home'))

    if request.method == 'POST':
        decision = (request.form.get('decision') or '').lower()
        if decision == 'decline':
            pending_record = PendingInvite.query.filter_by(token=token).first()
            if pending_record:
                pending_record.status = 'declined'
                db.session.commit()
            flash(f'You declined the link with {athlete.user.first_name} {athlete.user.last_name}.', 'info')
            return redirect(url_for('settings.settings_home'))

        pending_record = PendingInvite.query.filter_by(token=token).first()
        if pending_record:
            pending_record.status = 'accepted'

        coach_profile = _ensure_trainer_profile_for_user(current_user)
        athlete_profile = _ensure_athlete_profile_for_user(athlete.user)
        if athlete_profile not in coach_profile.athletes:
            coach_profile.athletes.append(athlete_profile)
        _ensure_role_flags(current_user)
        _ensure_role_flags(athlete.user)
        db.session.commit()

        flash(f'{athlete.user.first_name} {athlete.user.last_name} is now linked to your coaching roster.', 'success')
        session['selected_athlete_id'] = athlete.id
        return redirect(url_for('settings.settings_home'))

    return render_template(
        'invite_confirmation.html',
        title='Confirm trainer link',
        message=f'{athlete.user.first_name} {athlete.user.last_name} would like to be connected to your roster.',
        action_label='Accept trainer link',
        cancel_label='Decline link',
        action_url=url_for('settings.confirm_trainer_link', token=token),
        kind='trainer',
    )


@settings.route('/confirm/athlete/<token>', methods=['GET', 'POST'])
def confirm_athlete_link(token):
    payload = _decode_invite_token(token)
    if payload is None or payload.get('kind') != 'athlete_link':
        flash('This athlete link is invalid or expired.', 'warning')
        return redirect(url_for('settings.settings_home'))

    athlete_user = User.query.get(payload.get('athlete_id'))
    coach_user = User.query.get(payload.get('coach_id'))
    if athlete_user is None or coach_user is None:
        flash('This athlete link is no longer valid.', 'warning')
        return redirect(url_for('settings.settings_home'))

    if not current_user.is_authenticated:
        return redirect(url_for('auth.login'))
    if current_user.id != athlete_user.id:
        flash('This invitation is intended for the athlete account only.', 'warning')
        return redirect(url_for('settings.settings_home'))

    if request.method == 'POST':
        decision = (request.form.get('decision') or '').lower()
        if decision == 'decline':
            pending_record = PendingInvite.query.filter_by(token=token).first()
            if pending_record:
                pending_record.status = 'declined'
                db.session.commit()
            flash(f'You declined the link with {coach_user.first_name} {coach_user.last_name}.', 'info')
            return redirect(url_for('settings.settings_home'))

        pending_record = PendingInvite.query.filter_by(token=token).first()
        if pending_record:
            pending_record.status = 'accepted'

        athlete_profile = _ensure_athlete_profile_for_user(current_user)
        if payload.get('date_of_birth'):
            athlete_profile.date_of_birth = datetime.strptime(payload['date_of_birth'], '%Y-%m-%d').date()
        coach_profile = _ensure_trainer_profile_for_user(coach_user)
        if athlete_profile not in coach_profile.athletes:
            coach_profile.athletes.append(athlete_profile)
        _ensure_role_flags(current_user)
        _ensure_role_flags(coach_user)
        db.session.commit()

        flash(f'You are now linked to {coach_user.first_name} {coach_user.last_name}.', 'success')
        session['selected_athlete_id'] = athlete_profile.id
        return redirect(url_for('settings.settings_home'))

    return render_template(
        'invite_confirmation.html',
        title='Confirm athlete link',
        message=f'{coach_user.first_name} {coach_user.last_name} wants to add you as an athlete.',
        action_label='Accept link',
        cancel_label='Decline link',
        action_url=url_for('settings.confirm_athlete_link', token=token),
        kind='athlete',
    )


@settings.route('/athlete/add', methods=['GET', 'POST'])
def add_athlete():
    if not current_user.is_trainer and not current_user.is_athlete:
        abort(403)

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        sport = request.form.get('sport', '').strip() or 'running'
        dob = request.form.get('date_of_birth', '')

        if not email:
            flash('Please provide an athlete email.', 'warning')
            return redirect(url_for('settings.roster'))

        user = User.query.filter_by(email=email).first()
        if user is None:
            flash('No account was found for that email. Ask the athlete to register first.', 'warning')
            return redirect(url_for('settings.roster'))

        athlete = user.athlete_profile
        if athlete is None:
            athlete = Athlete(
                id=user.id,
                sport=sport,
                date_of_birth=datetime.strptime(dob, '%Y-%m-%d').date() if dob else None,
            )
            db.session.add(athlete)
            db.session.flush()

        if current_user.is_trainer and current_user.coach_profile:
            if athlete not in current_user.coach_profile.athletes:
                current_user.coach_profile.athletes.append(athlete)

        db.session.commit()
        session['selected_athlete_id'] = athlete.id
        flash(f'{user.first_name} {user.last_name} is now linked as an athlete.', 'success')
        return redirect(url_for('settings.roster'))

    return redirect(url_for('settings.settings_home'))


@settings.route('/athlete/<int:athlete_id>/calendar')
def athlete_calendar(athlete_id):
    athlete = Athlete.query.get_or_404(athlete_id)
    if not athlete_is_visible(athlete):
        abort(403)

    start_date = request.args.get('start_date')
    if start_date:
        try:
            active_day = datetime.strptime(start_date, '%Y-%m-%d').date()
        except ValueError:
            active_day = datetime.now().date()
    else:
        active_day = datetime.now().date()

    monday = active_day - timedelta(days=active_day.weekday())
    week_dates = [monday + timedelta(days=i) for i in range(7)]

    sessions_by_day = {}
    for current_day in week_dates:
        sessions_by_day[current_day.isoformat()] = []

    activities = Activity.query.filter_by(athlete_id=athlete.id).filter(
        Activity.date >= datetime.combine(monday, datetime.min.time()),
        Activity.date <= datetime.combine(monday + timedelta(days=6), datetime.max.time())
    ).all()

    planned_activities = PlannedActivity.query.filter_by(athlete_id=athlete.id).filter(
        PlannedActivity.planned_date >= datetime.combine(monday, datetime.min.time()),
        PlannedActivity.planned_date <= datetime.combine(monday + timedelta(days=6), datetime.max.time())
    ).all()

    for item in activities:
        day_key = item.date.date().isoformat()
        sessions_by_day.setdefault(day_key, []).append(item)
    for item in planned_activities:
        day_key = item.planned_date.date().isoformat()
        sessions_by_day.setdefault(day_key, []).append(item)

    return render_template(
        'settings.html',
        athlete=athlete,
        roster=get_roster_for_current_user(),
        selected_athlete=athlete,
        **get_athlete_overview_context(athlete),
        week_dates=week_dates,
        sessions_by_day=sessions_by_day,
        calendar_view=True,
    )


@settings.route('/athlete/<int:athlete_id>/plan', methods=['GET', 'POST'])
def create_plan(athlete_id):
    athlete = Athlete.query.get_or_404(athlete_id)
    if not athlete_is_visible(athlete):
        abort(403)

    if request.method == 'POST':
        planned_date = request.form.get('planned_date') or datetime.now().strftime('%Y-%m-%d')
        time_value = request.form.get('time', '08:00')
        scheduled_dt = datetime.strptime(f"{planned_date} {time_value}", '%Y-%m-%d %H:%M')

        planned = PlannedActivity(
            athlete_id=athlete.id,
            title=request.form.get('title', '').strip() or f"{request.form.get('activity_type', 'running').title()} Session",
            activity_type=request.form.get('activity_type', 'running'),
            planned_date=scheduled_dt,
            duration_seconds=max(int(request.form.get('duration_minutes', 0) or 0) * 60, 0),
            distance_km=float(request.form.get('distance_km', 0) or 0),
            intensity=request.form.get('intensity', 'moderate'),
            description=request.form.get('description', '').strip(),
        )
        db.session.add(planned)
        db.session.commit()
        flash('Training plan added successfully.', 'success')
        return redirect(url_for('settings.athlete_calendar', athlete_id=athlete.id))

    return render_template(
        'settings.html',
        athlete=athlete,
        roster=get_roster_for_current_user(),
        selected_athlete=athlete,
        plan_form=True,
        today=date.today(),
        **get_athlete_overview_context(athlete),
    )


@settings.route('/athlete/<int:athlete_id>/plan/<int:plan_id>/delete', methods=['POST'])
def delete_plan(athlete_id, plan_id):
    athlete = Athlete.query.get_or_404(athlete_id)
    if not athlete_is_visible(athlete):
        abort(403)

    planned = PlannedActivity.query.filter_by(id=plan_id, athlete_id=athlete.id).first_or_404()
    db.session.delete(planned)
    db.session.commit()
    flash('Planned session deleted.', 'success')
    return redirect(url_for('settings.athlete_calendar', athlete_id=athlete.id))
