import re
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import bcrypt
from flask import Flask, render_template_string
from flask_wtf.csrf import CSRFProtect
from wtforms import StringField

from app.admin.routes import (
    AdminCSRFForm,
    StravaTokenAdminView,
    UserAdminView,
    is_admin_user,
)
from app.settings import settings as settings_blueprint
from app.settings.routes import _get_pending_link_invite, add_athlete
from app.strava.auth import build_authorization_url, consume_oauth_state
from app.strava.routes import _get_strava_token_for_user
from app import create_app, update_schema
from app.models import User
from production_update import ensure_admin_account, run as run_production_update


class SecurityRegressionTests(unittest.TestCase):
    def test_default_admin_email_is_used_when_unset(self):
        settings = {
            'DB_COMPLETE_URL': 'sqlite://',
            'DATABASE_URL': '',
            'SECRET_KEY': 'test-key',
        }
        with patch.dict(os.environ, settings, clear=True), patch('app.load_dotenv'):
            app = create_app()
        self.assertEqual(app.config['ADMIN_EMAIL'], '1@admin.com')

    def test_production_update_requires_strong_admin_password_before_backup(self):
        settings = {'APP_ENV': 'production', 'ADMIN_PASSWORD': ''}
        with patch.dict(os.environ, settings, clear=True), patch('production_update.load_dotenv'):
            with patch('production_update.backup_database') as backup:
                with self.assertRaisesRegex(RuntimeError, 'ADMIN_PASSWORD must be configured'):
                    run_production_update(True)
                backup.assert_not_called()

    def test_configured_admin_can_login_and_open_admin_without_email(self):
        settings = {
            'DB_COMPLETE_URL': 'sqlite://',
            'DATABASE_URL': '',
            'SECRET_KEY': 'test-key',
            'ADMIN_EMAIL': 'admin@traininglows.local',
        }
        password = 'admin-password-for-tests-123'
        with patch.dict(os.environ, settings, clear=True), patch('app.load_dotenv'):
            app = create_app()
            update_schema(app)
            ensure_admin_account(app, password)

        with app.app_context():
            admin = User.query.filter_by(email='admin@traininglows.local').one()
            self.assertTrue(admin.verified_email)
            self.assertTrue(admin.is_trainer)
            self.assertIsNotNone(admin.coach_profile)
            self.assertTrue(bcrypt.checkpw(password.encode(), admin.password))

        client = app.test_client()
        login_page = client.get('/auth/login')
        csrf_token = re.search(
            rb'name="csrf_token" value="([^"]+)"',
            login_page.data,
        ).group(1).decode()
        response = client.post('/auth/login', data={
            'email': 'admin@traininglows.local',
            'password': password,
            'csrf_token': csrf_token,
        })
        self.assertEqual(response.status_code, 302)
        admin_page = client.get('/admin/')
        self.assertEqual(admin_page.status_code, 200)

    def test_mysql_url_uses_configured_port_and_escapes_credentials(self):
        settings = {
            'DB_COMPLETE_URL': '',
            'DATABASE_URL': '',
            'DB_USER': 'demo',
            'DB_PASSWORD': 'p@:/?#secret',
            'DB_HOSTNAME': 'db.example',
            'DB_PORT': '3307',
            'DB_NAME': 'training',
            'SECRET_KEY': 'test-key',
        }
        with patch.dict(os.environ, settings, clear=True), patch('app.load_dotenv'):
            app = create_app()
        database_url = app.config['SQLALCHEMY_DATABASE_URI']
        self.assertEqual(database_url.password, 'p@:/?#secret')
        self.assertEqual(database_url.port, 3307)
        self.assertEqual(database_url.database, 'training')

    def test_missing_database_configuration_fails_with_setting_names(self):
        settings = {
            'DB_COMPLETE_URL': '',
            'DATABASE_URL': '',
            'SECRET_KEY': 'test-key',
        }
        with patch.dict(os.environ, settings, clear=True), patch('app.load_dotenv'):
            with self.assertRaisesRegex(RuntimeError, 'DB_USER, DB_PASSWORD, DB_HOSTNAME, DB_NAME'):
                create_app()

    def test_admin_access_requires_configured_verified_identity(self):
        app = Flask(__name__)
        cases = (
            ('', True, 'admin@example.com', False),
            ('admin@example.com', False, 'admin@example.com', False),
            ('admin@example.com', True, 'other@example.com', False),
            ('admin@example.com', True, 'admin@example.com', True),
        )
        with app.app_context():
            for configured_email, verified, user_email, expected in cases:
                with self.subTest(configured_email=configured_email, verified=verified, user_email=user_email):
                    app.config['ADMIN_EMAIL'] = configured_email
                    user = Mock(is_authenticated=True, verified_email=verified, email=user_email)
                    with patch('app.admin.routes.current_user', user):
                        self.assertEqual(is_admin_user(), expected)

    def test_admin_csrf_field_is_not_copied_to_model(self):
        class TestForm(AdminCSRFForm):
            name = StringField(default='example')

        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test-key'
        with app.test_request_context('/'):
            form = TestForm()
            model = SimpleNamespace()
            form.populate_obj(model)
            self.assertEqual(model.name, 'example')
            self.assertFalse(hasattr(model, 'csrf_token'))

    def test_csrf_rejects_missing_token_and_accepts_valid_token(self):
        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test-key'
        CSRFProtect(app)
        app.add_url_rule(
            '/form',
            view_func=lambda: render_template_string(
                '<form method="post"><input name="csrf_token" value="{{ csrf_token() }}"></form>'
            ),
            endpoint='csrf_form',
        )
        app.add_url_rule('/submit', view_func=lambda: 'ok', methods=['POST'], endpoint='csrf_submit')
        client = app.test_client()
        response = client.get('/form')
        token = re.search(rb'name="csrf_token" value="([^"]+)"', response.data).group(1).decode()
        self.assertEqual(client.post('/submit').status_code, 400)
        self.assertEqual(client.post('/submit', data={'csrf_token': token}).status_code, 200)

    def test_unlinked_user_cannot_inherit_single_strava_token(self):
        user = SimpleNamespace(strava_athlete_id=None)
        self.assertIsNone(_get_strava_token_for_user(user))
        self.assertIsNone(user.strava_athlete_id)

    def test_strava_oauth_state_is_one_time_and_session_bound(self):
        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test-key'
        with app.test_request_context('/'):
            from flask import session
            session['strava_oauth_state'] = 'expected-state'
            self.assertTrue(consume_oauth_state('expected-state'))
            self.assertFalse(consume_oauth_state('expected-state'))
            session['strava_oauth_state'] = 'expected-state'
            self.assertFalse(consume_oauth_state('attacker-state'))

    def test_strava_authorization_url_encodes_parameters_and_stores_state(self):
        from urllib.parse import parse_qs, urlsplit
        from flask import session

        app = Flask(__name__)
        app.config.update(
            SECRET_KEY='test-key',
            STRAVA_CLIENT_ID='client&id',
            STRAVA_SCOPES='read,activity:read',
            PREFERRED_URL_SCHEME='https',
        )
        with app.test_request_context('/'), patch(
            'app.strava.auth.url_for',
            return_value='https://example.com/strava/callback',
        ):
            authorization_url = build_authorization_url()
            params = parse_qs(urlsplit(authorization_url).query)
            self.assertEqual(params['client_id'], ['client&id'])
            self.assertEqual(params['redirect_uri'], ['https://example.com/strava/callback'])
            self.assertEqual(params['scope'], ['read,activity:read'])
            self.assertEqual(params['state'], [session['strava_oauth_state']])

    def test_webhook_verification_is_public_but_fails_closed_without_token(self):
        app = Flask(__name__)
        app.config.update(
            SECRET_KEY='test-key',
            STRAVA_API_ACTIVE=True,
            STRAVA_WEBHOOK_VERIFY_TOKEN='',
        )
        from app.strava import strava as strava_blueprint
        app.register_blueprint(strava_blueprint, url_prefix='/strava')
        client = app.test_client()
        response = client.get('/strava/webhook?hub.verify_token=&hub.challenge=challenge')
        self.assertEqual(response.status_code, 403)
        app.config['STRAVA_WEBHOOK_VERIFY_TOKEN'] = 'expected-token'
        response = client.get('/strava/webhook?hub.verify_token=expected-token&hub.challenge=challenge')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'hub.challenge': 'challenge'})

    def test_link_confirmation_requires_matching_pending_invite(self):
        query = Mock()
        invite = object()
        query.filter_by.return_value.first.return_value = invite
        with patch('app.settings.routes.PendingInvite', SimpleNamespace(query=query)):
            self.assertIs(_get_pending_link_invite('signed-token', 'trainer_link', 10, 20), invite)
        query.filter_by.assert_called_once_with(
            token='signed-token',
            kind='trainer_link',
            from_user_id=10,
            to_user_id=20,
            status='pending',
        )

    def test_legacy_direct_athlete_link_does_not_mutate_roster(self):
        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test-key'
        app.register_blueprint(settings_blueprint, url_prefix='/settings')
        with app.test_request_context('/settings/athlete/add', method='POST'):
            response = add_athlete()
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.location.endswith('/settings/roster'))

    def test_admin_views_do_not_expose_credentials(self):
        self.assertFalse(UserAdminView.can_export)
        self.assertNotIn('password', UserAdminView.column_details_list)
        self.assertFalse(StravaTokenAdminView.can_export)
        self.assertFalse(StravaTokenAdminView.can_view_details)
        self.assertFalse(StravaTokenAdminView.can_edit)
        self.assertFalse(StravaTokenAdminView.can_delete)
        self.assertFalse(StravaTokenAdminView.can_create)
        self.assertNotIn('access_token', StravaTokenAdminView.column_list)
        self.assertNotIn('refresh_token', StravaTokenAdminView.column_list)

    def test_phase_color_validation_accepts_hex_only(self):
        from app.season.routes import _valid_phase_color
        self.assertEqual(_valid_phase_color('#198754'), '#198754')
        self.assertEqual(_valid_phase_color('#fff'), '#fff')
        self.assertEqual(_valid_phase_color('red'), '#6c757d')
        self.assertEqual(_valid_phase_color('#198754"><script>'), '#6c757d')
        self.assertEqual(_valid_phase_color(''), '#6c757d')
        self.assertEqual(_valid_phase_color(None), '#6c757d')

    def test_strava_title_sanitized_to_plain_text(self):
        from app.strava.routes import _sanitize_text, _strava_activity_from_payload
        self.assertEqual(_sanitize_text('<img src=x onerror=alert(1)>', 160), 'img src=x onerror=alert(1)')
        payload = {
            'id': 42,
            'name': '<script>alert(1)</script>Morning Run',
            'sport_type': 'Run',
            'start_date': '2026-10-01T06:00:00Z',
        }
        item = _strava_activity_from_payload(payload, user_id=1, athlete_id=2)
        self.assertNotIn('<', item.title)
        self.assertNotIn('>', item.title)
        self.assertLessEqual(len(item.title), 160)

    def test_webhook_rejects_activity_of_other_athlete(self):
        app = Flask(__name__)
        app.config.update(
            SECRET_KEY='test-key',
            STRAVA_API_ACTIVE=True,
            STRAVA_WEBHOOK_VERIFY_TOKEN='tok',
        )
        from app import cache, csrf
        from app.strava import strava as strava_blueprint
        app.register_blueprint(strava_blueprint, url_prefix='/strava')
        csrf.init_app(app)
        cache.init_app(app, config={'CACHE_TYPE': 'SimpleCache'})
        client = app.test_client()
        with patch('app.strava.routes.User') as user_model, \
             patch('app.strava.routes.strava_client') as strava_client:
            user_model.query.filter_by.return_value.first.return_value = SimpleNamespace(id=7, strava_auto_update=False)
            strava_client.get_activity.return_value = {'id': 99, 'athlete': {'id': 12345}, 'name': 'Not yours'}
            response = client.post('/strava/webhook', json={
                'object_type': 'activity',
                'aspect_type': 'create',
                'owner_id': 555,
                'object_id': 99,
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'status': 'ignored'})

    def test_rate_limit_blocks_after_threshold(self):
        from app import cache
        from app.rate_limit import enforce_rate_limit

        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test-key'
        cache.init_app(app, config={'CACHE_TYPE': 'SimpleCache'})

        @app.route('/limited', methods=['POST'])
        def limited():
            enforce_rate_limit('test-endpoint', 2, 60)
            return 'ok'

        client = app.test_client()
        self.assertEqual(client.post('/limited').status_code, 200)
        self.assertEqual(client.post('/limited').status_code, 200)
        self.assertEqual(client.post('/limited').status_code, 429)

    def test_send_email_fails_closed_in_production_without_transport(self):
        from app.email_utils import FAILED, SENT, send_email

        app = Flask(__name__)
        app.config.update(
            SECRET_KEY='test-key',
            BREVO_API_KEY='',
            MAIL_SERVER='',
            MAIL_DEFAULT_SENDER='',
        )
        with patch.dict(os.environ, {'APP_ENV': 'production'}):
            with app.test_request_context('/'):
                self.assertEqual(send_email('s', 'text', '<p>text</p>', ['a@b.com'], dev_fallback_url='https://x'), FAILED)
        with patch.dict(os.environ, {'APP_ENV': 'development'}):
            with app.test_request_context('/'):
                self.assertEqual(send_email('s', 'text', '<p>text</p>', ['a@b.com'], dev_fallback_url='https://x'), SENT)

    def test_register_does_not_confirm_existing_verified_account(self):
        from app import db

        settings = {
            'DB_COMPLETE_URL': 'sqlite://',
            'DATABASE_URL': '',
            'SECRET_KEY': 'test-key',
        }
        with patch.dict(os.environ, settings, clear=True), patch('app.load_dotenv'):
            app = create_app()
            update_schema(app)
        with app.app_context():
            db.session.add(User(
                first_name='Existing', last_name='User',
                email='taken@example.com',
                password=bcrypt.hashpw(b'their-password', bcrypt.gensalt()),
                verified_email=True,
            ))
            db.session.commit()

        client = app.test_client()
        page = client.get('/auth/register')
        csrf_token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
        response = client.post('/auth/register', data={
            'first_name': 'Mallory',
            'last_name': 'Attacker',
            'email': 'taken@example.com',
            'gender': 'other',
            'is_athlete': 'on',
            'password': 'attacker-pass',
            'confirm_password': 'attacker-pass',
            'main_sport': 'running',
            'date_of_birth': '1990-01-01',
            'csrf_token': csrf_token,
        }, follow_redirects=True)
        self.assertNotIn(b'already exists', response.data)
        self.assertNotIn(b'already verified', response.data)
        with app.app_context():
            # The verified account must be untouched and not duplicated.
            users = User.query.filter_by(email='taken@example.com').all()
            self.assertEqual(len(users), 1)
            self.assertEqual(users[0].first_name, 'Existing')

    def test_verify_email_page_does_not_reveal_verified_accounts(self):
        from app import db

        settings = {
            'DB_COMPLETE_URL': 'sqlite://',
            'DATABASE_URL': '',
            'SECRET_KEY': 'test-key',
        }
        with patch.dict(os.environ, settings, clear=True), patch('app.load_dotenv'):
            app = create_app()
            update_schema(app)
        with app.app_context():
            db.session.add(User(
                first_name='Existing', last_name='User',
                email='known@example.com',
                password=bcrypt.hashpw(b'their-password', bcrypt.gensalt()),
                verified_email=True,
            ))
            db.session.commit()
        client = app.test_client()
        response = client.get('/auth/verify_email?email=known@example.com')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'already verified', response.data)


if __name__ == '__main__':
    unittest.main()
