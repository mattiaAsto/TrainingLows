"""Production WSGI entrypoint for Gunicorn and Render."""
from app import db, create_app
from app.models import User
from sqlalchemy import MetaData


app = create_app()


with app.app_context():

    hashed_password = 1

    admin = User(
    first_name = "Trainer",
    last_name = "Trainer",
    email = "1@admin.com",
    password = hashed_password,
    verified_email = True,
    is_trainer = True,
    )

    meta = MetaData()
    
    meta.reflect(bind=db.engine)
    meta.drop_all(bind=db.engine)
    print("----- DB DROPPED -----")

    db.create_all()

    db.session.add(admin)
    db.session.commit()

