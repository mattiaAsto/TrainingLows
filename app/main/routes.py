from flask import render_template, request, redirect, url_for, session, flash, jsonify
from . import main
from app.models import *
from app import db, cache
from werkzeug.security import check_password_hash
from flask_login import login_required, login_manager, current_user
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import distinct
import os
import json
import time
import random


@main.route("/home")
def home():
    return render_template("main_base.html")



