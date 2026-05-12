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
    email = "Admin",
    password = hashed_password,
    verified_email = True
)

with app.app_context():

    #erase all the tables in the schema and recreate
    meta = MetaData()

    meta.reflect(bind=db.engine)
    meta.drop_all(bind=db.engine)

    db.create_all()


    db.session.add(admin)
    db.session.commit()

    print("Admin added to database")

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