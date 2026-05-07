from app import db
from datetime import datetime, timezone, timedelta
from flask_login import UserMixin, login_manager
from sqlalchemy.types import LargeBinary
from sqlalchemy import inspect, func
from zoneinfo import ZoneInfo
import random

class Athlete(UserMixin, db.Model):
    __tablename__="user"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(30), nullable=False)
    surname = db.Column(db.String(30), nullable=False)
    username = db.Column(db.String(120), unique=True, nullable=False)
    nickname = db.Column(db.String(80), nullable=False)
    password = db.Column(LargeBinary, nullable=False)
    society = db.Column(db.String(80), nullable=False, default="UNKNOWN")
    has_image = db.Column(db.Boolean, nullable=False, default=False)