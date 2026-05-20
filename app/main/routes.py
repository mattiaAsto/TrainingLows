from flask import render_template, request, redirect, url_for, session, flash, jsonify
from . import main
from app.models import *
from app import db, cache
from werkzeug.security import check_password_hash
from flask_login import login_manager, current_user, login_user, logout_user
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo
from sqlalchemy import distinct
import os
import json
import time
import random
import bcrypt


@main.context_processor
def global_injection_dictionary():

    return {
        "user": current_user,
    }


@main.route("/")
def home():
    return render_template("main_base.html")


@main.route("/test")
def test():
    admin = User.query.first()
    admin.athlete_profile = Athlete(
        sport = "running",
        date_of_birth = date(2005, 12, 16)
    )
    db.session.commit()

    admin.athlete_profile.create_activities_table()

    return render_template("test.html")


