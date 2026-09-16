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
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parent
REQUIRED_DEFINITION_KEYS = {'label', 'color', 'unit', 'category', 'model'}
VALID_DATATYPES = {'text', 'integer', 'float', 'boolean', 'select'}
REQUIRED_COLUMNS = {
    'Users': {'strava_auto_update'},
    'Athletes': {'self_reported_state', 'self_reported_note', 'self_reported_at'},
    'planned_activities': {'specific_data'},
    'Activities': {'specific_data'},
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


def run(apply):
    definitions = load_catalog()
    check_catalog_models(definitions) if apply else None
    if not apply:
        print(f'Catalog check passed: {len(definitions)} activity types.')
        print('No database changes were made. Use --apply --yes to continue.')
        return

    app_env = os.getenv('APP_ENV', '').lower()
    if app_env != 'production':
        raise RuntimeError('Refusing to apply without APP_ENV=production.')

    from app import create_app
    from app.models import get_activity_model
    from app import db

    url = make_url(os.getenv('DB_COMPLETE_URL') or os.getenv('DATABASE_URL', ''))
    if not url.drivername:
        raise RuntimeError('DB_COMPLETE_URL or DATABASE_URL must be configured.')
    backup_path = backup_database(url, ROOT / 'backups')
    print(f'Backup created: {backup_path}')

    app = create_app()
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
