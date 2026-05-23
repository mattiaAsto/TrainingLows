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
    return True if len(pw) >= 1 else False


@auth.route("/login", methods = ['GET', 'POST'])
def login():

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        remember = request.form.get("remember")

        # Validate inputs
        if not email or not password:
            return render_template("login.html", error="Email and password are required")

        # Find user by email
        user = User.query.filter_by(email=email).first()

        if user and bcrypt.checkpw(password.encode('utf-8'), user.password):
            # Password is correct
            login_user(user, remember=bool(remember))
            flash(f"Welcome back, {user.first_name}!", "success")
            return redirect(url_for("main.home"))
        else:
            # Invalid email or password
            return render_template("login.html", error="Invalid email or password")

    return render_template("login.html")


@auth.route("/register", methods = ['GET', 'POST'])
def register():

    if request.method == "POST":
        first_name = request.form["first_name"]
        last_name = request.form["last_name"]
        email = request.form["email"]
        gender = request.form["gender"]
        is_athlete = request.form.get("is_athlete") is not None
        is_coach = request.form.get("is_coach") is not None
        password = request.form["password"]
        confirm_password = request.form["confirm_password"] 
        if not check_pw(password):
            return render_template("register.html", error="Password must be at least 8 characters long")
        elif password != confirm_password:
            return render_template("register.html", error="Passwords do not match")

        existing = User.query.filter_by(email=email).first()
        if existing and not existing.verified_email:
            db.session.delete(existing)
            db.session.commit()
        
        user = User(
            first_name = first_name,
            last_name = last_name,
            email = email,
            password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()),
        )
        db.session.add(user)
        db.session.flush()  # Flush to get user.id before commit


        if is_athlete:
            main_sport = request.form["main_sport"]
            date_of_birth = request.form["date_of_birth"]

            athlete_profile = Athlete(
                id = user.id,
                sport = main_sport,
                date_of_birth = datetime.strptime(date_of_birth, '%Y-%m-%d').date(),
            )

            db.session.add(athlete_profile)

        if is_coach:
            specializtion = request.form["specialization"]
            bio = request.form["bio"]

            coach_profile = Coach(
                id = user.id,
                specialization = specializtion,
                bio = bio,
            )

            db.session.add(coach_profile)
        
        db.session.commit()

        return redirect(url_for("auth.verify_email", email=email, name = first_name))
    
    return render_template("register.html")
        




@auth.route("/verify_email")
def verify_email():

    return render_template("register.html")


@auth.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))

