from flask import Blueprint, redirect, url_for
from flask_login import current_user

settings = Blueprint(
    "settings",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="settings/static"
)

@settings.before_request
def require_login():
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login'))

from . import routes
