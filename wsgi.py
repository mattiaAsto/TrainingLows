"""Production WSGI entrypoint for Gunicorn and Render."""
from app import create_app

app = create_app()
