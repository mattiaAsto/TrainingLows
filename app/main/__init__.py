from flask import Blueprint, redirect, url_for
from flask_login import current_user

main = Blueprint(
    "main", __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="main/static"
)

@main.before_request
def require_login():
    """Require login for all routes in this blueprint"""
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login'))

from . import routes