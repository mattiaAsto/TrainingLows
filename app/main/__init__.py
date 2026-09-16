from flask import Blueprint, redirect, request, url_for
from flask_login import current_user

main = Blueprint(
    "main", __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="main/static"
)

@main.before_request
def require_login():
    """Keep the homepage preview public while protecting the application routes."""
    if not current_user.is_authenticated and request.endpoint != 'main.home':
        return redirect(url_for('auth.login'))

from . import routes