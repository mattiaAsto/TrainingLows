from flask import render_template, request, redirect, url_for, session, flash, jsonify
from . import main
from app.models import *
from app import db, cache
from werkzeug.security import check_password_hash
from flask_login import login_manager, current_user, login_user, logout_user
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo
from sqlalchemy import distinct
from app.strava.client import *
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
    
    list_ = get_activities(current_user.strava_athlete_id, per_page=2)
    print(list_)
    return jsonify(list_)

