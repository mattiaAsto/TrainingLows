from flask import Blueprint

planner = Blueprint(
    "planner",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="planner/static"
)

@planner.before_request
def require_login():
    from flask_login import current_user
    from flask import redirect, url_for
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login'))

from . import routes
