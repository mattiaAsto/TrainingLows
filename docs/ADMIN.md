# Administrator Account

The administrator is a normal `User` record with trainer access and a `Coach` profile. The production updater creates or updates this account before Gunicorn starts; no verification email is sent.

## Render Setup

In the Render web service's **Environment** settings, set:

- `ADMIN_EMAIL`: the admin login address. It defaults to `1@admin.com`. It must look like an email address, but it does not need to receive mail.
- `ADMIN_PASSWORD`: the admin login password. Use a unique password with at least 16 characters. Keep it in Render's environment settings, not in source control.

The release updater marks the account as verified so it can sign in without an email-verification step. It also gives the account trainer access and creates the associated coach profile. On each production update, the configured password is applied to this account; changing `ADMIN_PASSWORD` in Render and deploying rotates the admin login password.

Configure the Render **Pre-Deploy Command** as:

```sh
APP_ENV=production python production_update.py --apply --yes
```

The pre-deploy command must complete successfully before the new Gunicorn workers start. It takes a database backup before applying schema updates and provisioning the admin account.

## Sign In

Open the deployed app's `/auth/login` page and enter `ADMIN_EMAIL` and `ADMIN_PASSWORD`. After signing in, open `/admin/` for the administration panel. The admin navigation link appears for the configured account.

The old seeded account used `1@admin.com`; the updater reuses that account by default and replaces its old password with `ADMIN_PASSWORD`. Set a different `ADMIN_EMAIL` in Render if you prefer another login address.
