# TrainingLows
I just try to create my own trainingpeaks to coach athletes

## Production Updates

Never run `run.py` in production. It is a destructive local development seed script and now refuses to start when `APP_ENV=production`.

Validate a release without changing the database:

```text
python production_update.py --check
```

Apply a production update with an explicit confirmation:

PowerShell:

```powershell
$env:APP_ENV = 'production'
python production_update.py --apply --yes
```

Render shell:

```sh
APP_ENV=production python production_update.py --apply --yes
```

Run this as a release step before starting or replacing Gunicorn workers. The WSGI app does not create or alter tables at worker startup, avoiding concurrent schema changes across workers.
The production updater provisions the admin account from `ADMIN_EMAIL` and `ADMIN_PASSWORD` before Gunicorn starts. See [docs/ADMIN.md](docs/ADMIN.md) for Render setup and login instructions.

## Application branding

Set `APP_NAME` and `SHORT_APP_NAME` in your local `.env` file or in Render's service environment variables to change the displayed app name and its short label. The defaults are `TrainingLows` and `TL`.

```text
APP_NAME=TrainingLows
SHORT_APP_NAME=TL
```

For Render/Gunicorn, use the import-safe WSGI entrypoint as the start command:

```text
gunicorn --bind 0.0.0.0:$PORT wsgi:app
```

`wsgi.py` imports only the application factory. It never imports the local seed logic from `run.py`.

The update routine validates `activity_definitions.json`, creates a timestamped backup in `backups/` with `mysqldump` or `pg_dump`, starts the application schema updater, validates required columns, and confirms that catalog activity models load. It does not seed data or drop tables. The database backup must succeed before schema work begins.

Strava polling is not started by Gunicorn workers. To keep the six-hour fallback sync, add a Render Cron Job using the same repository and environment variables, scheduled every six hours, with `python strava_sync.py` as its command.
