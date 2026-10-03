"""Safe production update routine for TrainingLows.

Usage:
    python production_update.py --check
    python production_update.py --apply --yes

This script never imports run.py. The latter is a destructive local seed script.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.exc import ArgumentError
from sqlalchemy.engine import make_url
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
REQUIRED_DEFINITION_KEYS = {'label', 'color', 'unit', 'category', 'model'}
VALID_DATATYPES = {'text', 'integer', 'float', 'boolean', 'select'}
REQUIRED_COLUMNS = {
    'Users': {'strava_auto_update', 'activity_tint_enabled'},
    'Athletes': {'self_reported_state', 'self_reported_note', 'self_reported_at'},
    'planned_activities': {'specific_data'},
    'Activities': {'specific_data', 'average_heartrate'},
    'support_threads': {'user_last_read_at'},
}


def load_catalog():
    path = ROOT / 'app' / 'activity_definitions.json'
    with path.open(encoding='utf-8') as file:
        definitions = json.load(file)
    if not definitions:
        raise RuntimeError('Activity catalog is empty.')
    for activity_type, definition in definitions.items():
        missing = REQUIRED_DEFINITION_KEYS - definition.keys()
        if missing:
            raise RuntimeError(f'{activity_type}: missing catalog keys: {sorted(missing)}')
        for field_name, field in definition.get('specific_data', {}).items():
            datatype = field.get('datatype', 'text')
            if datatype not in VALID_DATATYPES:
                raise RuntimeError(f'{activity_type}.{field_name}: unsupported datatype {datatype!r}')
            if datatype == 'select' and not field.get('options'):
                raise RuntimeError(f'{activity_type}.{field_name}: select fields require options')
    return definitions


def backup_database(url, backup_dir):
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup_dir.mkdir(parents=True, exist_ok=True)
    if url.drivername.startswith('sqlite'):
        source = Path(url.database).resolve()
        destination = backup_dir / f'traininglows-{timestamp}.sqlite'
        shutil.copy2(source, destination)
        return destination
    if url.drivername.split('+', 1)[0] in {'postgres', 'postgresql'}:
        destination = backup_dir / f'traininglows-{timestamp}.dump'
        command = [
            'pg_dump', '--format=custom', '--no-owner', '--no-privileges',
            '--host', url.host or 'localhost',
            '--port', str(url.port or 5432),
            '--username', url.username or '',
            '--file', str(destination),
            '--dbname', url.database or '',
        ]
        environment = os.environ.copy()
        if url.password:
            environment['PGPASSWORD'] = url.password
        for option in ('sslmode', 'sslrootcert', 'sslcert', 'sslkey'):
            value = url.query.get(option)
            if value:
                environment[f'PG{option.upper()}'] = str(value)
        try:
            subprocess.run(command, check=True, env=environment, capture_output=True, text=True)
        except FileNotFoundError as error:
            raise RuntimeError('pg_dump was not found. Install the PostgreSQL client or create a verified backup before using --apply.') from error
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or '').strip()
            raise RuntimeError(f'Database backup failed: {detail or "pg_dump returned an error"}') from error
        return destination
    if url.drivername not in {'mysql', 'mysql+pymysql'}:
        raise RuntimeError(f'Automatic backups are not implemented for {url.drivername}.')

    destination = backup_dir / f'traininglows-{timestamp}.sql'
    command = ['mysqldump', '--single-transaction', '--routines', '--triggers', '--host', url.host or 'localhost', '--port', str(url.port or 3306), '--user', url.username or '', '--result-file', str(destination), url.database or '']
    environment = os.environ.copy()
    if url.password:
        environment['MYSQL_PWD'] = url.password
    try:
        subprocess.run(command, check=True, env=environment, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise RuntimeError('mysqldump was not found. Install it or create a verified backup before using --apply.') from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or '').strip()
        raise RuntimeError(f'Database backup failed: {detail or "mysqldump returned an error"}') from error
    return destination


def validate_schema(app):
    inspector = inspect(app.extensions['sqlalchemy'].engine)
    missing = {}
    for table, columns in REQUIRED_COLUMNS.items():
        existing = {column['name'] for column in inspector.get_columns(table)}
        absent = sorted(columns - existing)
        if absent:
            missing[table] = absent
    if missing:
        raise RuntimeError(f'Schema validation failed: {missing}')


def check_catalog_models(definitions):
    from app.models import get_activity_model
    for activity_type, definition in definitions.items():
        model = get_activity_model(activity_type)
        if model.__name__ != definition['model']:
            raise RuntimeError(f'{activity_type}: expected model {definition["model"]!r}, got {model.__name__!r}')


def ensure_admin_account(app, password):
    import bcrypt
    from app import db
    from app.models import Coach, User

    email = app.config['ADMIN_EMAIL']
    password_bytes = password.encode('utf-8')
    with app.app_context():
        try:
            admin = User.query.filter_by(email=email).with_for_update().first()
            if admin is None:
                admin = User(
                    first_name='Admin',
                    last_name='Admin',
                    email=email,
                    password=bcrypt.hashpw(password_bytes, bcrypt.gensalt()),
                    verified_email=True,
                    is_trainer=True,
                )
                db.session.add(admin)
                db.session.flush()
            else:
                try:
                    password_matches = bcrypt.checkpw(password_bytes, admin.password)
                except ValueError:
                    password_matches = False
                if not password_matches:
                    admin.password = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
                admin.verified_email = True
                admin.is_trainer = True

            if admin.coach_profile is None:
                db.session.add(Coach(
                    id=admin.id,
                    specialization='General',
                    bio='TrainingLows administrator',
                ))
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception('Could not provision the configured administrator account')
            raise


def run(apply):
    load_dotenv()
    definitions = load_catalog()
    check_catalog_models(definitions) if apply else None
    if not apply:
        print(f'Catalog check passed: {len(definitions)} activity types.')
        print('No database changes were made. Use --apply --yes to continue.')
        return

    app_env = os.getenv('APP_ENV', '').lower()
    if app_env != 'production':
        raise RuntimeError('Refusing to apply without APP_ENV=production.')
    admin_password = os.getenv('ADMIN_PASSWORD', '')
    if len(admin_password) < 16:
        raise RuntimeError('ADMIN_PASSWORD must be configured with at least 16 characters.')

    from app import create_app, update_schema
    from app.models import get_activity_model
    from app import db

    database_url = os.getenv('DB_COMPLETE_URL') or os.getenv('DATABASE_URL')
    if not database_url:
        raise RuntimeError('DB_COMPLETE_URL or DATABASE_URL must be configured.')
    try:
        url = make_url(database_url)
    except ArgumentError as error:
        raise RuntimeError('DB_COMPLETE_URL or DATABASE_URL must be a valid SQLAlchemy URL.') from error
    backup_path = backup_database(url, ROOT / 'backups')
    print(f'Backup created: {backup_path}')

    app = create_app()
    update_schema(app)
    ensure_admin_account(app, admin_password)
    with app.app_context():
        validate_schema(app)
        for activity_type in definitions:
            get_activity_model(activity_type)
        db.session.rollback()
    print(f'Production update complete: {len(definitions)} activity types available.')


def main():
    parser = argparse.ArgumentParser(description='Safely validate or apply a TrainingLows production update.')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='Validate the activity catalog without changing the database.')
    mode.add_argument('--apply', action='store_true', help='Backup the database, apply startup schema updates, and validate.')
    parser.add_argument('--yes', action='store_true', help='Required with --apply; confirms the production change.')
    args = parser.parse_args()
    if args.apply and not args.yes:
        parser.error('--apply requires --yes to prevent accidental production changes.')
    try:
        run(args.apply)
    except Exception as error:
        print(f'PRODUCTION UPDATE FAILED: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
