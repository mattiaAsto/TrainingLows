from app import db
from flask_login import UserMixin
from sqlalchemy.types import LargeBinary


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


class Coach(db.Model):
    __tablename__ = "Coaches"

    id = db.Column(db.Integer, db.ForeignKey("Users.id"), primary_key=True)
    specialization = db.Column(db.String(50), nullable=True)
    bio = db.Column(db.Text, nullable=True)

    user = db.relationship("User", back_populates="coach_profile")
    athletes = db.relationship("Athlete", secondary=CoachAthlete, back_populates="coaches")

    

