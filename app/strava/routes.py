from flask import render_template, redirect, url_for, request, session, flash
from flask_login import current_user
from . import strava
from app import db
from app.models import *
from app.strava.auth import build_authorization_url, exchange_code, get_valid_token
from app.strava import client as strava_client


@strava.context_processor
def global_injection_dictionary():
    return {
        "user": current_user,
    }


# ── Connect / OAuth flow ───────────────────────────────────────────────────────

@strava.route("/connect")
def connect():
    """Redirect the athlete to Strava's OAuth consent page."""
    return redirect(build_authorization_url())


@strava.route("/callback")
def callback():
    """
    Strava redirects here after the athlete grants or denies access.
    Exchanges the one-time code for access + refresh tokens.
    """
    error = request.args.get("error")
    if error:
        flash("Strava connection was denied. Please try again.", "danger")
        return redirect(url_for("strava.settings"))

    code = request.args.get("code")
    if not code:
        flash("Invalid callback — missing authorisation code.", "danger")
        return redirect(url_for("strava.settings"))

    try:
        token = exchange_code(code)
        #Optionally store athlete_id on the user model if you have that column:
        current_user.strava_athlete_id = token.athlete_id
        db.session.commit()
        flash("Strava account connected successfully!", "success")
    except Exception as e:
        flash(f"Could not connect Strava: {str(e)}", "danger")

    return redirect(url_for("strava.settings"))


@strava.route("/disconnect")
def disconnect():
    """Remove the stored Strava token for the current athlete."""
    from app.models import StravaToken
    token = StravaToken.query.filter_by(athlete_id=current_user.strava_athlete_id).first()
    if token:
        db.session.delete(token)
        db.session.commit()
        flash("Strava account disconnected.", "info")
    return redirect(url_for("strava.settings"))


# ── Settings page (connect / status) ──────────────────────────────────────────

@strava.route("/settings")
def settings():
    """
    Page where the user connects or manages their Strava account.
    Passes `connected=True/False` and the athlete profile if connected.
    """
    from app.models import StravaToken

    connected = False
    athlete   = None

    # Check if current user has a stored token
    athlete_id = getattr(current_user, "strava_athlete_id", None)
    if athlete_id:
        token = StravaToken.query.filter_by(athlete_id=athlete_id).first()
        if token:
            try:
                athlete   = strava_client.get_athlete(athlete_id)
                connected = True
            except Exception:
                # Token might be invalid — treat as disconnected
                print("invalid token")
                connected = False

    return render_template(
        "settings.html",
        connected=connected,
        athlete=athlete,
    )