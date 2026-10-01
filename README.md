# TrainingLows
I just try to create my own trainingpeaks to coach athletes

## Production Updates

Never run `run.py` in production. It is a destructive local development seed script and now refuses to start when `APP_ENV=production`.

Validate a release without changing the database:

```text
python production_update.py --check
```

Apply a production update with an explicit confirmation:

```text
set APP_ENV=production
python production_update.py --apply --yes
```

Run this as a release step before starting or replacing Gunicorn workers. The WSGI app does not create or alter tables at worker startup, avoiding concurrent schema changes across workers.
On a fresh database, register and verify the administrator account (`1@admin.com`) before opening `/admin`; Gunicorn no longer inserts a default-password account.

For Render/Gunicorn, use the import-safe WSGI entrypoint as the start command:

```text
gunicorn --bind 0.0.0.0:$PORT wsgi:app
```

`wsgi.py` imports only the application factory. It never imports the local seed logic from `run.py`.

The update routine validates `activity_definitions.json`, creates a timestamped backup in `backups/`, starts the application schema updater, validates required columns, and confirms that catalog activity models load. It does not seed data or drop tables. The database backup must succeed before schema work begins.
