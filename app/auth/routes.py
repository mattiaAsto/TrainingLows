from flask import render_template, request, redirect, url_for, session, current_app, flash, jsonify
from flask_mail import Message
from flask_login import login_user, logout_user, current_user
from . import auth
from app.models import *
from app import db, mail
from werkzeug.security import check_password_hash
from sqlalchemy import func
import os
import json
import bcrypt
import time
import random


def check_pw(pw):
    return len(pw) >= 8


def _build_verification_token(email):
    return current_app.url_serializer.dumps({"email": email}, salt="email-verification")


def _send_verification_email(user):
    token = _build_verification_token(user.email)
    verification_url = url_for("auth.verify_email_token", token=token, _external=True)

    if current_app.config.get("MAIL_SERVER") and current_app.config.get("MAIL_DEFAULT_SENDER"):
        msg = Message(
            subject="Verify your TrainingLows account",
            recipients=[user.email],
            sender=current_app.config.get("MAIL_DEFAULT_SENDER"),
            body=(
                f"Hi {user.first_name},\n\n"
                f"Please verify your account by clicking the link below:\n{verification_url}\n\n"
                "If you did not create this account, you can ignore this email."
            )
        )
        try:
            mail.send(msg)
            return True
        except Exception:
            return False

    flash(f"Verification link: {verification_url}", "info")
    return True


@auth.route("/login", methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember')

        if not email or not password:
            return render_template('login.html', error='Email and password are required')

        user = User.query.filter_by(email=email).first()
        if user and bcrypt.checkpw(password.encode('utf-8'), user.password):
            if not user.is_verified:
                flash('Please verify your email before logging in.', 'warning')
                return redirect(url_for('auth.verify_email', email=email))
            login_user(user, remember=bool(remember))
            flash(f'Welcome back, {user.first_name}!', 'success')
            return redirect(url_for('main.home'))

        return render_template('login.html', error='Invalid email or password')

    return render_template('login.html')


@auth.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
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
            return render_template('register.html', error='Password must be at least 8 characters long')
        if password != confirm_password:
            return render_template('register.html', error='Passwords do not match')

        existing = User.query.filter_by(email=email).first()
        if existing and not existing.verified_email:
            db.session.delete(existing)
            db.session.commit()
        elif existing and existing.verified_email:
            return render_template('register.html', error='An account with this email already exists.')

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
        _send_verification_email(user)
        return redirect(url_for('auth.verify_email', email=email))

    return render_template('register.html')


@auth.route('/verify_email', methods=['GET', 'POST'])
def verify_email():
    email = request.args.get('email', '').strip().lower()
    user = User.query.filter_by(email=email).first() if email else None
    if user and user.verified_email:
        flash('Your email is already verified.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('verify_email.html', email=email, user=user)


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
    flash('Your email has been verified successfully. You can now log in.', 'success')
    return redirect(url_for('auth.login'))


@auth.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

