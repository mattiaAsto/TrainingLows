from app import create_app, db
from datetime import datetime, timezone
from livereload import Server
import os
import logging
import json
from app.models import *
from datetime import datetime, timedelta, timezone
from sqlalchemy import MetaData
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import time
import os
import bcrypt
import random





app = create_app() 

admin_password = str(os.getenv("ADMIN_PASSWORD", "1"))            
hashed_password=bcrypt.hashpw(admin_password.encode('utf-8'), bcrypt.gensalt())

admin = User(
    first_name = "Admin",
    last_name = "Admin",
    email = "1@admin.com",
    password = hashed_password,
    verified_email = True
)

with app.app_context():

    #erase all the tables in the schema and recreate
    meta = MetaData()

    meta.reflect(bind=db.engine)
    meta.drop_all(bind=db.engine)
    print("----- DB DROPPED -----")

    db.create_all()


    db.session.add(admin)
    db.session.commit()

    print("Admin added to database")
    # create an Athlete profile for the admin user (if not present) and add a default activity dated today
    try:
        if not Athlete.query.get(admin.id):
            athlete = Athlete(id=admin.id, sport='running', date_of_birth=None)
            db.session.add(athlete)
            db.session.commit()
            print(f"Athlete profile created for admin (id={admin.id})")
    except Exception as e:
        print("Warning creating athlete profile:", e)

    


    try:
        existing = Activity.query.filter_by(athlete_id=admin.id).first()
        if not existing:
            now = datetime.now()

            running_titles = ["Morning Run", "Evening Run", "Trail Run", "Long Run", "Recovery Run"]
            swimming_titles = ["Pool Session", "Open Water Swim", "Interval Swim", "Easy Swim"]
            cycling_titles = ["Road Ride", "Mountain Bike", "Evening Ride", "Long Ride", "Recovery Ride"]
            strength_titles = ["Upper Body", "Lower Body", "Full Body", "Core Session", "Power Training"]

            for _ in range(100):
                days_ago = random.randint(0, 84)
                random_date = now - timedelta(days=days_ago,
                                            hours=random.randint(0, 23),
                                            minutes=random.randint(0, 59))

                activity_type = random.choice(["running", "swimming", "cycling", "strength"])

                if activity_type == "running":
                    activity = Running(
                        athlete_id=admin.id,
                        title=random.choice(running_titles),
                        duration_seconds=random.randint(1800, 7200),
                        distance_km=round(random.uniform(3.0, 25.0), 1),
                        calories_burned=random.randint(200, 900),
                        elevation_gain_m=round(random.uniform(0, 300), 1),
                        intensity=random.choice(['low', 'moderate', 'high']),
                        description='Auto-generated running activity',
                        date=random_date,
                        pace_min_km=round(random.uniform(4.0, 7.0), 2),
                        surface=random.choice(['road', 'trail', 'track'])
                    )

                elif activity_type == "swimming":
                    activity = Swimming(
                        athlete_id=admin.id,
                        title=random.choice(swimming_titles),
                        duration_seconds=random.randint(1800, 5400),
                        distance_km=round(random.uniform(0.5, 5.0), 1),
                        calories_burned=random.randint(200, 700),
                        elevation_gain_m=0,
                        intensity=random.choice(['low', 'moderate', 'high']),
                        description='Auto-generated swimming activity',
                        date=random_date,
                        pool_length_m=random.choice([25, 50]),
                        strokes=random.choice(['freestyle', 'backstroke', 'breaststroke', 'butterfly']),
                        water_type=random.choice(['pool', 'ocean', 'lake'])
                    )

                elif activity_type == "cycling":
                    activity = Cycling(
                        athlete_id=admin.id,
                        title=random.choice(cycling_titles),
                        duration_seconds=random.randint(3600, 14400),
                        distance_km=round(random.uniform(10.0, 120.0), 1),
                        calories_burned=random.randint(300, 1200),
                        elevation_gain_m=round(random.uniform(0, 1500), 1),
                        intensity=random.choice(['low', 'moderate', 'high']),
                        description='Auto-generated cycling activity',
                        date=random_date,
                        speed_km_h=round(random.uniform(15.0, 40.0), 1),
                        bike_type=random.choice(['road', 'mountain', 'hybrid']),
                        terrain=random.choice(['road', 'trail', 'mixed'])
                    )

                else:  # strength
                    activity = Strenght(
                        athlete_id=admin.id,
                        title=random.choice(strength_titles),
                        duration_seconds=random.randint(1800, 5400),
                        distance_km=None,
                        calories_burned=random.randint(150, 600),
                        elevation_gain_m=None,
                        intensity=random.choice(['low', 'moderate', 'high']),
                        description='Auto-generated strength activity',
                        date=random_date,
                        strenght_type=random.choice(['maximal', 'resistance', 'power'])
                    )

                db.session.add(activity)

            db.session.commit()
            print(f"100 random activities created for athlete {admin.id}")

    except Exception as e:
        db.session.rollback()
        print("Warning creating default activities:", e)

system=1

host = os.getenv("HOST", "127.0.0.1")
port = int(os.getenv("PORT", 5500))

if __name__ == '__main__':
    print("Refreshed...")

    
    if system == 1:
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)
        app.run(host=host, port=port, debug=True)
    else:
        server = Server(app)
        # Aggiungi qui i file o directory che vuoi monitorare
        server.watch('app/main/static/*.css')  # Monitora i file CSS nella cartella static/css
        server.watch('app/main/templates/*.html')  # Monitora i file HTML nei templates
        server.serve(debug=True, port=8000)