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


@auth.route("/register")
def register():
    return render_template("register.html")


@auth.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))

