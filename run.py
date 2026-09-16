from app import create_app, db
from datetime import datetime, timezone
from livereload import Server
import os
import logging
import json
from app.models import *
from app.activity_catalog import ACTIVITY_DEFINITIONS, ACTIVITY_TYPES, activity_label
from datetime import datetime, timedelta, timezone
from sqlalchemy import MetaData
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import time
import os
import bcrypt
import random





use_debug = True
db_dropping = False

if not use_debug and __name__ == '__main__':
    print('Debug disabled. Start this module with: gunicorn --bind 0.0.0.0:$PORT wsgi:app')
    raise SystemExit(0)

if __name__ == '__main__' and os.getenv('APP_ENV', '').lower() == 'production':
    raise RuntimeError('run.py is a destructive development seed script. Use production_update.py for production changes.')

app = create_app()

if __name__ == '__main__' and use_debug and not db_dropping:
    print('Debug mode without database reset.')
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host=os.getenv('HOST', '127.0.0.1'), port=int(os.getenv('PORT', 5500)), debug=False, use_reloader=False)
    raise SystemExit(0)

admin_password = str(os.getenv("ADMIN_PASSWORD", "1"))            
hashed_password=bcrypt.hashpw(admin_password.encode('utf-8'), bcrypt.gensalt())

admin = User(
    first_name = "Trainer",
    last_name = "Trainer",
    email = "1@admin.com",
    password = hashed_password,
    verified_email = True,
    is_trainer = True,
)
admin2 = User(
    first_name = "Athlete",
    last_name = "Athlete",
    email = "2@admin.com",
    password = hashed_password,
    verified_email = True,
    is_athlete = True,
)

with app.app_context():

    #erase all the tables in the schema and recreate
    meta = MetaData()

    meta.reflect(bind=db.engine)
    meta.drop_all(bind=db.engine)
    print("----- DB DROPPED -----")

    db.create_all()


    db.session.add(admin)
    db.session.add(admin2)
    db.session.commit()

    print("Admin added to database")
    # Keep the debug users' role flags and profiles consistent for local testing.
    try:
        if not Athlete.query.get(admin.id):
            athlete = Athlete(id=admin.id, sport='running', date_of_birth=None)
            db.session.add(athlete)
            print(f"Athlete profile created for admin (id={admin.id})")
        if not Athlete.query.get(admin2.id):
            athlete2 = Athlete(id=admin2.id, sport='running', date_of_birth=None)
            db.session.add(athlete2)
            print(f"Athlete profile created for athlete (id={admin2.id})")
        if not Coach.query.get(admin.id):
            coach = Coach(id=admin.id, specialization='General', bio='Debug trainer')
            db.session.add(coach)
            print(f"Coach profile created for admin (id={admin.id})")
        db.session.commit()
    except Exception as e:
        print("Warning creating athlete profile:", e)

    


    try:
        existing = Activity.query.filter_by(athlete_id=admin.id).first()
        if not existing:
            now = datetime.now() # + timedelta(days=10)

            running_titles = ["Morning Run", "Evening Run", "Trail Run", "Long Run", "Recovery Run"]
            swimming_titles = ["Pool Session", "Open Water Swim", "Interval Swim", "Easy Swim"]
            cycling_titles = ["Road Ride", "Mountain Bike", "Evening Ride", "Long Ride", "Recovery Ride"]
            strength_titles = ["Upper Body", "Lower Body", "Full Body", "Core Session", "Power Training"]

            for _ in range(100):
                days_ago = random.randint(0, 84)
                random_date = now - timedelta(days=days_ago,
                                            hours=random.randint(0, 23),
                                            minutes=random.randint(0, 59))

                activity_type = random.choice(list(ACTIVITY_TYPES))
                duration = random.randint(1800, 7200) if activity_type != "cycling" else random.randint(3600, 14400)
                
                # Distribute duration across 5 zones randomly
                zone_splits = [random.randint(0, 100) for _ in range(5)]
                total_splits = sum(zone_splits) or 1
                timez1 = int(duration * zone_splits[0] / total_splits)
                timez2 = int(duration * zone_splits[1] / total_splits)
                timez3 = int(duration * zone_splits[2] / total_splits)
                timez4 = int(duration * zone_splits[3] / total_splits)
                timez5 = duration - timez1 - timez2 - timez3 - timez4

                if activity_type == "running":
                    activity = get_activity_model('running')(
                        athlete_id=admin.id,
                        title=random.choice(running_titles),
                        duration_seconds=duration,
                        distance_km=round(random.uniform(3.0, 25.0), 1),
                        calories_burned=random.randint(200, 900),
                        elevation_gain_m=round(random.uniform(0, 300), 1),
                        intensity=random.choice(['low', 'moderate', 'high']),
                        timez1_seconds=timez1,
                        timez2_seconds=timez2,
                        timez3_seconds=timez3,
                        timez4_seconds=timez4,
                        timez5_seconds=timez5,
                        description='Auto-generated running activity',
                        date=random_date,
                        pace_min_km=round(random.uniform(4.0, 7.0), 2),
                        surface=random.choice(['road', 'trail', 'track'])
                    )

                elif activity_type == "swimming":
                    activity = get_activity_model('swimming')(
                        athlete_id=admin.id,
                        title=random.choice(swimming_titles),
                        duration_seconds=random.randint(1800, 5400),
                        distance_km=round(random.uniform(0.5, 5.0), 1),
                        calories_burned=random.randint(200, 700),
                        elevation_gain_m=0,
                        intensity=random.choice(['low', 'moderate', 'high']),
                        timez1_seconds=timez1,
                        timez2_seconds=timez2,
                        timez3_seconds=timez3,
                        timez4_seconds=timez4,
                        timez5_seconds=timez5,
                        description='Auto-generated swimming activity',
                        date=random_date,
                        pool_length_m=random.choice([25, 50]),
                        strokes=random.choice(['freestyle', 'backstroke', 'breaststroke', 'butterfly']),
                        water_type=random.choice(['pool', 'ocean', 'lake'])
                    )

                elif activity_type == "cycling":
                    activity = get_activity_model('cycling')(
                        athlete_id=admin.id,
                        title=random.choice(cycling_titles),
                        duration_seconds=duration,
                        distance_km=round(random.uniform(10.0, 120.0), 1),
                        calories_burned=random.randint(300, 1200),
                        elevation_gain_m=round(random.uniform(0, 1500), 1),
                        intensity=random.choice(['low', 'moderate', 'high']),
                        timez1_seconds=timez1,
                        timez2_seconds=timez2,
                        timez3_seconds=timez3,
                        timez4_seconds=timez4,
                        timez5_seconds=timez5,
                        description='Auto-generated cycling activity',
                        date=random_date,
                        speed_km_h=round(random.uniform(15.0, 40.0), 1),
                        bike_type=random.choice(['road', 'mountain', 'hybrid']),
                        terrain=random.choice(['road', 'trail', 'mixed'])
                    )

                elif activity_type == "strength":
                    activity = get_activity_model('strength')(
                        athlete_id=admin.id,
                        title=random.choice(strength_titles),
                        duration_seconds=random.randint(1800, 5400),
                        distance_km=None,
                        calories_burned=random.randint(150, 600),
                        elevation_gain_m=None,
                        intensity=random.choice(['low', 'moderate', 'high']),
                        timez1_seconds=timez1,
                        timez2_seconds=timez2,
                        timez3_seconds=timez3,
                        timez4_seconds=timez4,
                        timez5_seconds=timez5,
                        description='Auto-generated strength activity',
                        date=random_date,
                        strenght_type=random.choice(['maximal', 'resistance', 'power'])
                    )

                else:
                    model_cls = get_activity_model(activity_type)
                    activity = model_cls(
                        athlete_id=admin.id,
                        title=f"{activity_label(activity_type)} Session",
                        duration_seconds=duration,
                        distance_km=round(random.uniform(2.0, 40.0), 1) if ACTIVITY_DEFINITIONS[activity_type]['unit'] == 'km' else None,
                        calories_burned=random.randint(100, 800),
                        elevation_gain_m=round(random.uniform(0, 800), 1),
                        intensity=random.choice(['low', 'moderate', 'high']),
                        timez1_seconds=timez1,
                        timez2_seconds=timez2,
                        timez3_seconds=timez3,
                        timez4_seconds=timez4,
                        timez5_seconds=timez5,
                        description=f'Auto-generated {activity_label(activity_type).lower()} activity',
                        date=random_date,
                    )

                db.session.add(activity)

            db.session.commit()
            print(f"100 random activities created for athlete {admin.id}")

            planned_templates = [
                ("Tempo Run", "running", 3, 12.0, "moderate", "Planned workout for debug"),
                ("Hill Repeats", "running", 4, 10.5, "high", "Strength workout for debug"),
                ("Recovery Ride", "cycling", 2, 32.0, "low", "Easy spin"),
                ("Threshold Ride", "cycling", 3, 48.0, "high", "Planned debug ride"),
                ("Pool Intervals", "swimming", 1, 2.2, "moderate", "Technique set"),
                ("Open Water", "swimming", 2, 3.5, "moderate", "Long distance swim"),
                ("Upper Body Strength", "strength", 1, 0, "moderate", "Upper body plan"),
                ("Lower Body Strength", "strength", 1, 0, "high", "Leg strength plan"),
                ("Easy Run", "running", 2, 8.0, "low", "Recovery run"),
                ("Long Ride", "cycling", 4, 80.0, "moderate", "Long endurance ride"),
            ]

            for index, (title, activity_type, hours, distance_km, intensity, description) in enumerate(planned_templates):
                planned = PlannedActivity(
                    athlete_id=admin.id,
                    title=title,
                    activity_type=activity_type,
                    planned_date=now + timedelta(days=index + 1, hours=8 + (index % 3) * 2),
                    duration_seconds=hours * 3600,
                    distance_km=distance_km if activity_type != 'strength' else 0,
                    intensity=intensity,
                    description=description,
                )
                db.session.add(planned)

            for index in range(10):
                activity_type = random.choice(["running", "cycling", "swimming", "strength"])
                title = {
                    "running": "Debug Run",
                    "cycling": "Debug Ride",
                    "swimming": "Debug Swim",
                    "strength": "Debug Strength",
                }[activity_type]
                db.session.add(PlannedActivity(
                    athlete_id=admin.id,
                    title=f"{title} {index + 1}",
                    activity_type=activity_type,
                    planned_date=now + timedelta(days=7 + index, hours=18),
                    duration_seconds=random.randint(1800, 5400),
                    distance_km=round(random.uniform(4.0, 45.0), 1) if activity_type != 'strength' else 0,
                    intensity=random.choice(['low', 'moderate', 'high']),
                    description='Auto-generated planned debug activity',
                ))

            db.session.commit()
            print("20 planned debug activities created")

    except Exception as e:
        db.session.rollback()
        print("Warning creating default activities:", e)

system=1

host = os.getenv("HOST", "127.0.0.1")
port = int(os.getenv("PORT", 5500))

if __name__ == '__main__':
    if not use_debug:
        print('Debug disabled. Start this module with: gunicorn --bind 0.0.0.0:$PORT wsgi:app')
        raise SystemExit(0)

    print("Refreshed...")

    if system == 1:
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)
        app.run(host=host, port=port, debug=False, use_reloader=False)
    else:
        server = Server(app)
        # Aggiungi qui i file o directory che vuoi monitorare
        server.watch('app/main/static/*.css')  # Monitora i file CSS nella cartella static/css
        server.watch('app/main/templates/*.html')  # Monitora i file HTML nei templates
        server.serve(debug=True, port=8000)