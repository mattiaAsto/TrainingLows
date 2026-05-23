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
        # only add a default activity if the athlete has no activities yet
        existing = Activity.query.filter_by(athlete_id=admin.id).first()
        if not existing:
            now = datetime.now()
            default_run = Running(
                athlete_id=admin.id,
                title = "prova",
                duration_seconds=3600,
                distance_km=10.0,
                calories_burned=600,
                elevation_gain_m=50.0,
                intensity='moderate',
                description='Default run created at setup',
                date=now
            )
            db.session.add(default_run)
            db.session.commit()
            print(f"Default activity created (id={default_run.id}) for athlete {admin.id}")
    except Exception as e:
        print("Warning creating default activity:", e)

    try:
        # only add a default activity if the athlete has no activities yet
        existing = Activity.query.filter_by(athlete_id=admin.id).first()
        if existing:
            now = datetime.now() + timedelta(days=-6)
            default_run = Running(
                athlete_id=admin.id,
                title = "prova",
                duration_seconds=3600,
                distance_km=10.0,
                calories_burned=600,
                elevation_gain_m=50.0,
                intensity='moderate',
                description='Default run created at setup',
                date=now
            )
            db.session.add(default_run)
            db.session.commit()
            print(f"Default activity created (id={default_run.id}) for athlete {admin.id}")
    except Exception as e:
        print("Warning creating default activity:", e)

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