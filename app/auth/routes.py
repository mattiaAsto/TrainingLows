from flask import render_template, request, redirect, url_for, session, current_app, flash, jsonify
from flask_login import login_user, logout_user, current_user
from . import auth
from app.models import *
from app import db
from app.email_utils import build_verification_email, send_email
from app.rate_limit import enforce_rate_limit
from werkzeug.security import check_password_hash
from sqlalchemy import func
import os
import json
import bcrypt
import time
import random


def check_pw(pw):
    # bcrypt only uses the first 72 bytes; longer inputs would be silently
    # truncated, so reject them instead of pretending they are distinct.
    return bool(pw) and len(pw) >= 8 and len(pw.encode('utf-8')) <= 72


# Dummy hash compared against when the login email is unknown, so the response
# time does not reveal whether an account exists for a given address.
_DUMMY_HASH = bcrypt.hashpw(b'timing-equalizer', bcrypt.gensalt())


def _build_verification_token(email):
    return current_app.url_serializer.dumps({"email": email}, salt="email-verification")


def _build_resend_token(email):
    return current_app.url_serializer.dumps({"email": email}, salt="email-resend")


def _read_resend_token(token):
    try:
        payload = current_app.url_serializer.loads(token, salt="email-resend", max_age=60 * 10)
    except Exception:
        return None
    return payload.get("email")


def _send_verification_email(user):
    token = _build_verification_token(user.email)
    verification_url = url_for("auth.verify_email_token", token=token, _external=True)
    subject, text_body, html_body = build_verification_email(user.first_name, verification_url)
    return send_email(
        subject,
        text_body,
        html_body,
        recipients=[user.email],
        dev_fallback_url=verification_url,
    )


@auth.route("/login", methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        enforce_rate_limit('login', 10, 60)
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember')

        if not email or not password:
            return render_template('login.html', error='Email and password are required')

        user = User.query.filter_by(email=email).first()
        password_bytes = password.encode('utf-8')
        if user is None:
            bcrypt.checkpw(password_bytes, _DUMMY_HASH)
        password_ok = user is not None and bcrypt.checkpw(password_bytes, user.password)
        if password_ok:
            if not user.is_verified:
                flash('Please verify your email before logging in.', 'warning')
                return redirect(url_for('auth.verify_email', email=email))
            # Drop any anonymous-session state (selected athlete, stale OAuth
            # state, ...) before establishing the authenticated session.
            session.clear()
            login_user(user, remember=bool(remember))
            flash(f'Welcome back, {user.first_name}!', 'success')
            return redirect(url_for('main.home'))

        return render_template('login.html', error='Invalid email or password')

    return render_template('login.html')


@auth.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        enforce_rate_limit('register', 5, 60)
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        gender = request.form.get('gender', '')
        is_athlete = request.form.get('is_athlete') is not None
        is_coach = request.form.get('is_coach') is not None
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not is_athlete and not is_coach:
            return render_template('register.html', error='Select at least one role: athlete or trainer.')
        if not first_name or not last_name or not email or not gender:
            return render_template('register.html', error='Please complete all required fields.')
        if not check_pw(password):
            return render_template('register.html', error='Password must be between 8 and 72 characters long')
        if password != confirm_password:
            return render_template('register.html', error='Passwords do not match')

        existing = User.query.filter_by(email=email).first()
        if existing and not existing.verified_email:
            db.session.delete(existing)
            db.session.commit()
        elif existing and existing.verified_email:
            # Generic response: never confirm that the address is already registered.
            flash('If that address can be registered, a verification email is on its way. Delivery can take 5-10 minutes.', 'info')
            return redirect(url_for('auth.verify_email', email=email))

        user = User(
            first_name=first_name,
            last_name=last_name,
            email=email,
            password=bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()),
            is_athlete=bool(is_athlete),
            is_trainer=bool(is_coach),
            is_verified=False,
        )
        db.session.add(user)
        db.session.flush()

        if is_athlete:
            main_sport = request.form.get('main_sport')
            date_of_birth = request.form.get('date_of_birth')
            if not main_sport or not date_of_birth:
                db.session.rollback()
                return render_template('register.html', error='Athlete profile requires sport and date of birth.')
            athlete_profile = Athlete(
                id=user.id,
                sport=main_sport,
                date_of_birth=datetime.strptime(date_of_birth, '%Y-%m-%d').date(),
            )
            db.session.add(athlete_profile)

        if is_coach:
            specialization = request.form.get('specialization')
            bio = request.form.get('bio', '')
            coach_profile = Coach(
                id=user.id,
                specialization=specialization,
                bio=bio,
            )
            db.session.add(coach_profile)

        db.session.commit()
        if _send_verification_email(user) == 'failed':
            flash('Your account was created, but the verification email could not be sent. Please try again later or contact support.', 'warning')
        return redirect(url_for('auth.verify_email', email=email))

    return render_template('register.html')


@auth.route('/verify_email', methods=['GET', 'POST'])
def verify_email():
    email = request.args.get('email', '').strip().lower()
    user = User.query.filter_by(email=email).first() if email else None
    if user and user.verified_email:
        # Render the same generic page for everyone; confirming that an
        # address is registered and verified would be an enumeration oracle.
        user = None

    resend_token = _build_resend_token(email) if user else None
    return render_template('verify_email.html', email=email, user=user, resend_token=resend_token)


@auth.route('/verify_email/resend', methods=['POST'])
def resend_verification_email():
    enforce_rate_limit('resend-verification', 3, 600)
    token = request.form.get('token', '')
    email = _read_resend_token(token)
    user = User.query.filter_by(email=email).first() if email else None

    if not user:
        # Do not reveal whether the address exists or the token expired.
        flash('If an unverified account exists for that address, a new verification email is on its way. Delivery can take 5-10 minutes.', 'info')
        return redirect(url_for('auth.verify_email', email=email or ''))

    if user.verified_email:
        flash('Your email is already verified.', 'success')
        return redirect(url_for('auth.login'))

    if _send_verification_email(user) == 'failed':
        flash('The verification email could not be sent right now. Please try again in a few minutes or contact support.', 'warning')
    else:
        flash('A new verification email is on its way. It can take 5-10 minutes to arrive; please also check your spam folder.', 'success')
    return redirect(url_for('auth.verify_email', email=user.email))


@auth.route('/verify_email/<token>')
def verify_email_token(token):
    try:
        payload = current_app.url_serializer.loads(token, salt='email-verification', max_age=60 * 60 * 24 * 7)
    except Exception:
        flash('This verification link is invalid or expired.', 'warning')
        return redirect(url_for('auth.verify_email'))

    email = payload.get('email')
    user = User.query.filter_by(email=email).first()
    if not user:
        flash('No matching user was found for this verification link.', 'warning')
        return redirect(url_for('auth.verify_email'))

    user.verified_email = True
    db.session.commit()
    if current_user.is_authenticated and current_user.id == user.id:
        flash('Your email has been verified successfully.', 'success')
        return redirect(url_for('settings.settings_home'))
    flash('Your email has been verified successfully. You can now log in.', 'success')
    return redirect(url_for('auth.login'))


@auth.route('/logout', methods=['POST'])
def logout():
    logout_user()
    return redirect(url_for('main.home'))

