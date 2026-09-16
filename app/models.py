from app import db
from app.activity_catalog import ACTIVITY_DEFINITIONS, ACTIVITY_TYPES
from flask_login import UserMixin
from sqlalchemy.types import LargeBinary, JSON
from datetime import datetime
from zoneinfo import ZoneInfo
import time


CoachAthlete = db.Table("CoachAthlete",
    db.Column("coach_id", db.Integer, db.ForeignKey("Coaches.id"), primary_key=True),
    db.Column("athlete_id", db.Integer, db.ForeignKey("Athletes.id"), primary_key=True)
)


class StravaToken(db.Model):
    """Stores per-athlete OAuth tokens."""

    __tablename__ = "strava_tokens"

    id            = db.Column(db.Integer, primary_key=True)
    athlete_id    = db.Column(db.BigInteger, unique=True, nullable=False, index=True)
    access_token  = db.Column(db.String(255), nullable=False)
    refresh_token = db.Column(db.String(255), nullable=False)
    expires_at    = db.Column(db.BigInteger, nullable=False)   # Unix timestamp
    scope         = db.Column(db.String(255), nullable=True)
    created_at    = db.Column(db.DateTime, server_default=db.func.now())
    updated_at    = db.Column(db.DateTime, server_default=db.func.now(),
                              onupdate=db.func.now())

    # ── Helpers ────────────────────────────────────────────────────────────────

    @property
    def is_expired(self) -> bool:
        """True when the access token has expired (with 60-s buffer)."""
        return time.time() > (self.expires_at - 60)

    def update_from_response(self, token_data: dict) -> None:
        """Overwrite fields from a Strava token-refresh response."""
        self.access_token  = token_data["access_token"]
        self.refresh_token = token_data["refresh_token"]
        self.expires_at    = token_data["expires_at"]

    def __repr__(self) -> str:
        return f"<StravaToken athlete_id={self.athlete_id}>"


class StravaActivity(db.Model):
    """Strava activity inbox and import history for one TrainingLows user."""
    __tablename__ = 'strava_activities'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'external_id', name='uq_strava_activity_user_external'),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id', ondelete='CASCADE'), nullable=False, index=True)
    external_id = db.Column(db.BigInteger, nullable=False)
    athlete_id = db.Column(db.BigInteger, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    title = db.Column(db.String(160), nullable=False)
    activity_type = db.Column(db.String(50), nullable=False, default='activity')
    started_at = db.Column(db.DateTime, nullable=False, index=True)
    duration_seconds = db.Column(db.Integer, nullable=True, default=0)
    distance_km = db.Column(db.Float, nullable=True, default=0)
    elevation_gain_m = db.Column(db.Float, nullable=True, default=0)
    calories_burned = db.Column(db.Integer, nullable=True)
    average_speed_km_h = db.Column(db.Float, nullable=True)
    average_heartrate = db.Column(db.Float, nullable=True)
    raw_payload = db.Column(db.Text, nullable=True)
    received_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo('Europe/Zurich')))
    reviewed_at = db.Column(db.DateTime, nullable=True)
    rejected_until = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref=db.backref('strava_activities', cascade='all, delete-orphan'))


class User(UserMixin, db.Model):
    __tablename__ = "Users"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    first_name = db.Column(db.String(30), nullable=False)
    last_name = db.Column(db.String(30), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(LargeBinary, nullable=False)
    verified_email = db.Column(db.Boolean, nullable=False, default=False)
    is_verified = db.synonym('verified_email')
    is_athlete = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    is_trainer = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    strava_athlete_id = db.Column(db.BigInteger, nullable=True, unique=True)
    strava_auto_update = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    activity_tint_enabled = db.Column(db.Boolean, nullable=False, default=True, server_default='1')

    athlete_profile = db.relationship("Athlete", back_populates="user", uselist=False, cascade="all, delete-orphan")
    coach_profile = db.relationship("Coach", back_populates="user", uselist=False, cascade="all, delete-orphan")

    @property
    def is_coach(self):
        return bool(self.is_trainer) or self.coach_profile is not None


class Athlete(db.Model):
    __tablename__ = "Athletes"

    id = db.Column(db.Integer, db.ForeignKey("Users.id", ondelete="CASCADE"), primary_key=True)
    sport = db.Column(db.String(50), nullable=True)
    date_of_birth = db.Column(db.Date, nullable=True)
    self_reported_state = db.Column(db.String(30), nullable=False, default='ready', server_default='ready')
    self_reported_note = db.Column(db.Text, nullable=True)
    self_reported_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", back_populates="athlete_profile")
    coaches = db.relationship("Coach", secondary=CoachAthlete, back_populates="athletes")
    activities = db.relationship("Activity", foreign_keys="Activity.athlete_id", backref="athlete", cascade="all, delete-orphan")


class Coach(db.Model):
    __tablename__ = "Coaches"

    id = db.Column(db.Integer, db.ForeignKey("Users.id", ondelete="CASCADE"), primary_key=True)
    specialization = db.Column(db.String(50), nullable=True)
    bio = db.Column(db.Text, nullable=True)

    user = db.relationship("User", back_populates="coach_profile")
    athletes = db.relationship("Athlete", secondary=CoachAthlete, back_populates="coaches")


class PendingInvite(db.Model):
    __tablename__ = "pending_invites"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    kind = db.Column(db.String(30), nullable=False)
    from_user_id = db.Column(db.Integer, db.ForeignKey("Users.id", ondelete="CASCADE"), nullable=False, index=True)
    to_user_id = db.Column(db.Integer, db.ForeignKey("Users.id", ondelete="CASCADE"), nullable=False, index=True)
    token = db.Column(db.String(255), nullable=False, unique=True, index=True)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo("Europe/Zurich")))

    from_user = db.relationship("User", foreign_keys=[from_user_id], backref="sent_invites")
    to_user = db.relationship("User", foreign_keys=[to_user_id], backref="received_invites")


class SupportThread(db.Model):
    __tablename__ = 'support_threads'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id', ondelete='SET NULL'), nullable=True, index=True)
    requester_email = db.Column(db.String(120), nullable=False, index=True)
    subject = db.Column(db.String(160), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='open', index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo('Europe/Zurich')))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo('Europe/Zurich')), onupdate=lambda: datetime.now(ZoneInfo('Europe/Zurich')))
    closed_at = db.Column(db.DateTime, nullable=True)
    user_last_read_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref=db.backref('support_threads', cascade='all, delete-orphan'))
    messages = db.relationship('SupportMessage', back_populates='thread', cascade='all, delete-orphan', order_by='SupportMessage.created_at.asc()')


class SupportMessage(db.Model):
    __tablename__ = 'support_messages'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    thread_id = db.Column(db.Integer, db.ForeignKey('support_threads.id', ondelete='CASCADE'), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('Users.id', ondelete='SET NULL'), nullable=True, index=True)
    author_email = db.Column(db.String(120), nullable=False)
    body = db.Column(db.Text, nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo('Europe/Zurich')))

    thread = db.relationship('SupportThread', back_populates='messages')
    author = db.relationship('User', backref='support_messages')


class PlannedActivity(db.Model):
    """Weekly training program for a given athlete, used for planned-vs-done comparisons."""
    __tablename__ = "planned_activities"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey("Athletes.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(80), nullable=False)
    activity_type = db.Column(db.String(30), nullable=False, index=True)
    planned_date = db.Column(db.DateTime, nullable=False, index=True)
    duration_seconds = db.Column(db.Integer, nullable=True, default=0)
    distance_km = db.Column(db.Float, nullable=True, default=0)
    intensity = db.Column(db.String(20), nullable=False, default="moderate")
    description = db.Column(db.Text, nullable=True)
    specific_data = db.Column(JSON, nullable=True, default=dict)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo("Europe/Zurich")))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo("Europe/Zurich")), onupdate=lambda: datetime.now(ZoneInfo("Europe/Zurich")))

    athlete = db.relationship("Athlete", backref=db.backref("planned_activities", cascade="all, delete-orphan"))

    def get_duration_formatted(self):
        hours = self.duration_seconds // 3600 if self.duration_seconds else 0
        minutes = (self.duration_seconds % 3600) // 60 if self.duration_seconds else 0
        seconds = self.duration_seconds % 60 if self.duration_seconds else 0

        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"


class DailyMetric(db.Model):
    """One recovery and wellbeing record per athlete and calendar date."""
    __tablename__ = "daily_metrics"
    __table_args__ = (
        db.UniqueConstraint('athlete_id', 'metric_date', name='uq_daily_metrics_athlete_date'),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey('Athletes.id', ondelete='CASCADE'), nullable=False, index=True)
    metric_date = db.Column(db.Date, nullable=False, index=True)
    sleep_duration_minutes = db.Column(db.Integer, nullable=True)
    sleep_quality_score = db.Column(db.Integer, nullable=True)  # 1-8 text scale
    resting_hr = db.Column(db.Float, nullable=True)
    hrv_ms = db.Column(db.Float, nullable=True)
    weight_kg = db.Column(db.Float, nullable=True)
    readiness_score = db.Column(db.Integer, nullable=True)
    temperature_c = db.Column(db.Float, nullable=True)
    soreness_score = db.Column(db.Integer, nullable=True)
    stress_score = db.Column(db.Integer, nullable=True)
    steps = db.Column(db.Integer, nullable=True)
    calories = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo('Europe/Zurich')))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo('Europe/Zurich')), onupdate=lambda: datetime.now(ZoneInfo('Europe/Zurich')))

    athlete = db.relationship('Athlete', backref=db.backref('daily_metrics', cascade='all, delete-orphan'))

    QUALITY_LABELS = {
        1: 'Very poor', 2: 'Poor', 3: 'Below average', 4: 'Fair',
        5: 'Good', 6: 'Very good', 7: 'Excellent', 8: 'Exceptional',
    }

    @property
    def sleep_quality_label(self):
        return self.QUALITY_LABELS.get(self.sleep_quality_score, 'Not recorded')


class TrainingSeason(db.Model):
    """A lazy-created January-to-December planning container for one athlete."""
    __tablename__ = 'training_seasons'
    __table_args__ = (
        db.UniqueConstraint('athlete_id', 'season_year', name='uq_training_season_athlete_year'),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey('Athletes.id', ondelete='CASCADE'), nullable=False, index=True)
    season_year = db.Column(db.Integer, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    generation_status = db.Column(db.String(30), nullable=False, default='draft')
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo('Europe/Zurich')))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo('Europe/Zurich')), onupdate=lambda: datetime.now(ZoneInfo('Europe/Zurich')))

    athlete = db.relationship('Athlete', backref=db.backref('training_seasons', cascade='all, delete-orphan'))
    objectives = db.relationship('TrainingObjective', back_populates='season', cascade='all, delete-orphan')
    phases = db.relationship('TrainingPhase', back_populates='season', cascade='all, delete-orphan', order_by='TrainingPhase.start_date')


class TrainingObjective(db.Model):
    """Race, test, milestone, or other season objective."""
    __tablename__ = 'training_objectives'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    season_id = db.Column(db.Integer, db.ForeignKey('training_seasons.id', ondelete='CASCADE'), nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    objective_type = db.Column(db.String(30), nullable=False, default='race')
    priority = db.Column(db.String(1), nullable=False, default='B')
    sport = db.Column(db.String(30), nullable=False, default='running')
    event_date = db.Column(db.Date, nullable=False, index=True)
    distance_km = db.Column(db.Float, nullable=True)
    location = db.Column(db.String(160), nullable=True)
    elevation_gain_m = db.Column(db.Float, nullable=True)
    terrain = db.Column(db.String(40), nullable=True)
    target_time_seconds = db.Column(db.Integer, nullable=True)
    target_pace = db.Column(db.Float, nullable=True)
    target_power = db.Column(db.Float, nullable=True)
    result_time_seconds = db.Column(db.Integer, nullable=True)
    result_placing = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='planned')
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo('Europe/Zurich')))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo('Europe/Zurich')), onupdate=lambda: datetime.now(ZoneInfo('Europe/Zurich')))

    season = db.relationship('TrainingSeason', back_populates='objectives')
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    phase_links = db.relationship('PhaseObjective', back_populates='objective', cascade='all, delete-orphan')


class TrainingPhase(db.Model):
    """Editable generated or manually-created period in an athlete season."""
    __tablename__ = 'training_phases'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    season_id = db.Column(db.Integer, db.ForeignKey('training_seasons.id', ondelete='CASCADE'), nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    phase_type = db.Column(db.String(30), nullable=False, default='custom')
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False, index=True)
    color = db.Column(db.String(20), nullable=False, default='#6c757d')
    description = db.Column(db.Text, nullable=True)
    generation_source = db.Column(db.String(30), nullable=False, default='manual')
    is_manually_edited = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo('Europe/Zurich')))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo('Europe/Zurich')), onupdate=lambda: datetime.now(ZoneInfo('Europe/Zurich')))

    season = db.relationship('TrainingSeason', back_populates='phases')
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    objective_links = db.relationship('PhaseObjective', back_populates='phase', cascade='all, delete-orphan')
    weekly_targets = db.relationship('PhaseWeeklyTarget', back_populates='phase', cascade='all, delete-orphan', order_by='PhaseWeeklyTarget.week_start')


class PhaseObjective(db.Model):
    """Many-to-many link between a phase and its objectives."""
    __tablename__ = 'phase_objectives'
    __table_args__ = (db.UniqueConstraint('phase_id', 'objective_id', name='uq_phase_objective'),)

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    phase_id = db.Column(db.Integer, db.ForeignKey('training_phases.id', ondelete='CASCADE'), nullable=False)
    objective_id = db.Column(db.Integer, db.ForeignKey('training_objectives.id', ondelete='CASCADE'), nullable=False)
    role = db.Column(db.String(30), nullable=False, default='secondary')

    phase = db.relationship('TrainingPhase', back_populates='objective_links')
    objective = db.relationship('TrainingObjective', back_populates='phase_links')


class PhaseWeeklyTarget(db.Model):
    """Weekly volume, load, and recovery targets for a phase."""
    __tablename__ = 'phase_weekly_targets'
    __table_args__ = (db.UniqueConstraint('phase_id', 'week_start', name='uq_phase_week'),)

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    phase_id = db.Column(db.Integer, db.ForeignKey('training_phases.id', ondelete='CASCADE'), nullable=False)
    week_start = db.Column(db.Date, nullable=False, index=True)
    target_duration_minutes = db.Column(db.Integer, nullable=True)
    target_distance_km = db.Column(db.Float, nullable=True)
    target_elevation_m = db.Column(db.Float, nullable=True)
    target_sessions = db.Column(db.Integer, nullable=True)
    target_tss = db.Column(db.Float, nullable=True)
    target_ctl = db.Column(db.Float, nullable=True)
    target_atl = db.Column(db.Float, nullable=True)
    target_sleep_hours = db.Column(db.Float, nullable=True)
    target_readiness = db.Column(db.Float, nullable=True)
    target_hrv_ms = db.Column(db.Float, nullable=True)
    target_resting_hr = db.Column(db.Float, nullable=True)
    focus = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    phase = db.relationship('TrainingPhase', back_populates='weekly_targets')


class Activity(db.Model):
    """Base Activity model with single-table inheritance"""
    __tablename__ = "Activities"
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey("Athletes.id"), nullable=False, index=True)
    title = db.Column(db.String(50), nullable=False, index=True)  # Discriminator column for inheritance
    activity_type = db.Column(db.String(50), nullable=False, index=True)  # Discriminator column for inheritance
    
    # Common attributes for all activities
    duration_seconds = db.Column(db.Integer, nullable=False)  # Duration in seconds
    distance_km = db.Column(db.Float, nullable=True)          # Distance in kilometers
    calories_burned = db.Column(db.Integer, nullable=True)    # Calories burned
    elevation_gain_m = db.Column(db.Float, nullable=True)     # Elevation gain in meters
    intensity = db.Column(db.String(20), nullable=False)      # "low", "moderate", "high"
    timez1_seconds = db.Column(db.Integer, nullable=True, default=0)  # Time in zone 1 (seconds)
    timez2_seconds = db.Column(db.Integer, nullable=True, default=0)  # Time in zone 2 (seconds)
    timez3_seconds = db.Column(db.Integer, nullable=True, default=0)  # Time in zone 3 (seconds)
    timez4_seconds = db.Column(db.Integer, nullable=True, default=0)  # Time in zone 4 (seconds)
    timez5_seconds = db.Column(db.Integer, nullable=True, default=0)  # Time in zone 5 (seconds)
    description = db.Column(db.Text, nullable=True)
    specific_data = db.Column(JSON, nullable=True, default=dict)
    date = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo("Europe/Zurich")), index=True)

    # Optional sport-specific fields live on the shared activity table so every
    # catalog-defined activity follows the same persistence shape.
    pace_min_km = db.Column(db.Float, nullable=True)
    surface = db.Column(db.String(30), nullable=True)
    pool_length_m = db.Column(db.Float, nullable=True)
    strokes = db.Column(db.String(50), nullable=True)
    water_type = db.Column(db.String(30), nullable=True)
    speed_km_h = db.Column(db.Float, nullable=True)
    bike_type = db.Column(db.String(30), nullable=True)
    terrain = db.Column(db.String(30), nullable=True)
    strenght_type = db.Column(db.String(30), nullable=True)
    
    # Polymorphic identity
    __mapper_args__ = {
        "polymorphic_on": activity_type,
        "polymorphic_identity": "activity"
    }

    @classmethod
    def get_activity_types(cls):
        return list(ACTIVITY_TYPES)
    
    def get_duration_formatted(self):
        """
        Convert duration_seconds to formatted string (h:m:s)
        
        Returns:
            str: Duration formatted as "1h 45m 30s" or "45m 30s" if less than 1 hour
        """
        hours = self.duration_seconds // 3600
        minutes = (self.duration_seconds % 3600) // 60
        seconds = self.duration_seconds % 60
        
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"
    
    def get_duration_dict(self):
        """
        Convert duration_seconds to a dictionary with hours, minutes, seconds
        
        Returns:
            dict: {"hours": int, "minutes": int, "seconds": int}
        """
        return {
            "hours": self.duration_seconds // 3600,
            "minutes": (self.duration_seconds % 3600) // 60,
            "seconds": self.duration_seconds % 60
        }


# Every activity model is generated from the JSON catalog. All generated models
# inherit the same shared Activity table and optional sport fields above.
_CATALOG_ACTIVITY_MODELS = {}
for _activity_type, _definition in ACTIVITY_DEFINITIONS.items():
    _class_name = _definition.get('model') or ''.join(part.capitalize() for part in _activity_type.split('_'))
    if _class_name == 'Activity':
        _class_name = ''.join(part.capitalize() for part in _activity_type.split('_'))
    catalog_model = type(
        _class_name,
        (Activity,),
        {
            '__module__': __name__,
            '__mapper_args__': {'polymorphic_identity': _activity_type},
        },
    )
    globals()[_class_name] = catalog_model
    _CATALOG_ACTIVITY_MODELS[_activity_type] = catalog_model


def get_activity_model(activity_type):
    return _CATALOG_ACTIVITY_MODELS.get(activity_type, Activity)