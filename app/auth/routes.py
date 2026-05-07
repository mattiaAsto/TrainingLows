from flask import render_template, request, redirect, url_for, session, current_app, flash, jsonify
from flask_mail import Message
from flask_login import login_user, logout_user
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



