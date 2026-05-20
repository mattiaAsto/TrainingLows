from app import db
from flask_login import UserMixin
from sqlalchemy.types import LargeBinary
from datetime import datetime
from zoneinfo import ZoneInfo


CoachAthlete = db.Table("CoachAthlete",
    db.Column("coach_id", db.Integer, db.ForeignKey("Coaches.id"), primary_key=True),
    db.Column("athlete_id", db.Integer, db.ForeignKey("Athletes.id"), primary_key=True)
)


class User(UserMixin, db.Model):
    __tablename__ = "Users"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    first_name = db.Column(db.String(30), nullable=False)
    last_name = db.Column(db.String(30), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(LargeBinary, nullable=False)
    verified_email = db.Column(db.Boolean, nullable=False, default=False)

    athlete_profile = db.relationship("Athlete", back_populates="user", uselist=False)
    coach_profile = db.relationship("Coach", back_populates="user", uselist=False)

    @property
    def is_athlete(self):
        return self.athlete_profile is not None

    @property
    def is_coach(self):
        return self.coach_profile is not None


class Athlete(db.Model):
    __tablename__ = "Athletes"

    id = db.Column(db.Integer, db.ForeignKey("Users.id"), primary_key=True)
    sport = db.Column(db.String(50), nullable=True)
    date_of_birth = db.Column(db.Date, nullable=True)

    user = db.relationship("User", back_populates="athlete_profile")
    coaches = db.relationship("Coach", secondary=CoachAthlete, back_populates="athletes")
    activities = db.relationship("Activity", foreign_keys="Activity.athlete_id", backref="athlete")


class Coach(db.Model):
    __tablename__ = "Coaches"

    id = db.Column(db.Integer, db.ForeignKey("Users.id"), primary_key=True)
    specialization = db.Column(db.String(50), nullable=True)
    bio = db.Column(db.Text, nullable=True)

    user = db.relationship("User", back_populates="coach_profile")
    athletes = db.relationship("Athlete", secondary=CoachAthlete, back_populates="coaches")


class Activity(db.Model):
    """Base Activity model with single-table inheritance"""
    __tablename__ = "Activities"
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey("Athletes.id"), nullable=False, index=True)
    activity_type = db.Column(db.String(50), nullable=False, index=True)  # Discriminator column for inheritance
    
    # Common attributes for all activities
    duration_seconds = db.Column(db.Integer, nullable=False)  # Duration in seconds
    distance_km = db.Column(db.Float, nullable=True)          # Distance in kilometers
    calories_burned = db.Column(db.Integer, nullable=True)    # Calories burned
    intensity = db.Column(db.String(20), nullable=False)      # "low", "moderate", "high"
    description = db.Column(db.Text, nullable=True)
    date = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(ZoneInfo("Europe/Zurich")), index=True)
    
    # Polymorphic identity
    __mapper_args__ = {
        "polymorphic_on": activity_type,
        "polymorphic_identity": "activity"
    }
    
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


class Running(Activity):
    """Running activity - inherits from Activity"""
    __mapper_args__ = {
        "polymorphic_identity": "running"
    }
    
    # Running-specific attributes
    pace_km_h = db.Column(db.Float, nullable=True)        # Average pace in km/h
    elevation_gain_m_running = db.Column(db.Float, nullable=True) # Elevation gain in meters
    surface = db.Column(db.String(30), nullable=True)     # "road", "trail", "track"


class Swimming(Activity):
    """Swimming activity - inherits from Activity"""
    __mapper_args__ = {
        "polymorphic_identity": "swimming"
    }
    
    # Swimming-specific attributes
    pool_length_m = db.Column(db.Float, nullable=True)  # Pool length in meters
    strokes = db.Column(db.String(50), nullable=True)   # "freestyle", "backstroke", "breaststroke", "butterfly"
    water_type = db.Column(db.String(30), nullable=True) # "pool", "ocean", "lake"


class Cycling(Activity):
    """Cycling activity - inherits from Activity"""
    __mapper_args__ = {
        "polymorphic_identity": "cycling"
    }
    
    # Cycling-specific attributes
    speed_km_h = db.Column(db.Float, nullable=True)       # Average speed in km/h
    elevation_gain_m_cycling = db.Column(db.Float, nullable=True) # Elevation gain in meters
    bike_type = db.Column(db.String(30), nullable=True)   # "road", "mountain", "hybrid"
    terrain = db.Column(db.String(30), nullable=True)     # "road", "trail", "mixed"
