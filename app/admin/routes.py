from datetime import datetime
from zoneinfo import ZoneInfo

from flask import abort, current_app, redirect, request, url_for
from flask_admin import Admin, AdminIndexView, BaseView, expose
from flask_admin.contrib.sqla import ModelView
from flask_mail import Message
from flask_login import current_user

from app import db, mail
from app.activity_catalog import ACTIVITY_TYPES
from app.models import (
    Activity,
    Athlete,
    Coach,
    DailyMetric,
    PendingInvite,
    PhaseObjective,
    PhaseWeeklyTarget,
    PlannedActivity,
    StravaActivity,
    StravaToken,
    SupportMessage,
    SupportThread,
    TrainingObjective,
    TrainingPhase,
    TrainingSeason,
    User,
    get_activity_model,
)


ADMIN_EMAIL = '1@admin.com'


def is_admin_user():
    return current_user.is_authenticated and current_user.email.lower() == ADMIN_EMAIL


class AdminAccessMixin:
    def is_accessible(self):
        return is_admin_user()

    def inaccessible_callback(self, name, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login', next=request.url))
        abort(403)


class AdminModelView(AdminAccessMixin, ModelView):
    can_view_details = True
    can_export = True
    page_size = 25
    column_display_pk = True
    details_modal = True
    edit_modal = False
    create_modal = False

    def __init__(self, model, session, **kwargs):
        super().__init__(model, session, **kwargs)
        self._configure_columns()

    def _configure_columns(self):
        columns = [column.name for column in self.model.__table__.columns]
        self.column_searchable_list = [name for name in columns if name in {'email', 'first_name', 'last_name', 'title', 'activity_type', 'status', 'name', 'sport'}]
        self.column_filters = [name for name in columns if name in {'id', 'athlete_id', 'user_id', 'activity_type', 'status', 'intensity', 'metric_date', 'planned_date', 'date', 'event_date', 'season_year'}]
        self.column_default_sort = ('id', True) if 'id' in columns else None


class UserAdminView(AdminModelView):
    column_list = ('id', 'first_name', 'last_name', 'email', 'is_athlete', 'is_trainer', 'verified_email', 'strava_auto_update')
    column_searchable_list = ('email', 'first_name', 'last_name')
    column_filters = ('is_athlete', 'is_trainer', 'verified_email', 'strava_auto_update')
    form_excluded_columns = ('password', 'athlete_profile', 'coach_profile', 'sent_invites', 'received_invites', 'strava_activities')
    column_exclude_list = ('password',)


class AthleteAdminView(AdminModelView):
    column_list = ('id', 'user', 'sport', 'date_of_birth', 'self_reported_state', 'self_reported_at', 'coaches')
    column_searchable_list = ('sport', 'self_reported_state')
    column_filters = ('sport', 'self_reported_state')
    form_excluded_columns = ('user', 'activities', 'planned_activities', 'daily_metrics', 'training_seasons', 'coaches')


class CoachAdminView(AdminModelView):
    column_list = ('id', 'user', 'specialization', 'athletes')
    column_searchable_list = ('specialization',)
    form_excluded_columns = ('user',)


class ActivityAdminView(AdminModelView):
    column_list = ('id', 'athlete', 'title', 'activity_type', 'date', 'duration_seconds', 'distance_km', 'intensity', 'calories_burned')
    column_searchable_list = ('title', 'activity_type', 'intensity')
    column_filters = ('activity_type', 'intensity', 'date', 'athlete_id')
    form_excluded_columns = ('athlete',)


class SupportAdminView(AdminAccessMixin, BaseView):
    @expose('/')
    def index(self):
        status = request.args.get('status', 'open')
        query = SupportThread.query.order_by(SupportThread.updated_at.desc())
        if status in {'open', 'closed'}:
            query = query.filter_by(status=status)
        return self.render('admin/support/index.html', threads=query.all(), active_status=status)

    @expose('/thread/<int:thread_id>', methods=['GET', 'POST'])
    def thread(self, thread_id):
        thread = SupportThread.query.get_or_404(thread_id)
        if request.method == 'POST':
            action = request.form.get('action', 'reply')
            body = (request.form.get('message') or '').strip()
            if action in {'close', 'reopen'}:
                thread.status = 'closed' if action == 'close' else 'open'
                thread.closed_at = datetime.now(ZoneInfo('Europe/Zurich')) if action == 'close' else None
            elif body:
                db.session.add(SupportMessage(thread_id=thread.id, author_id=current_user.id, author_email=current_user.email, body=body, is_admin=True))
                thread.status = 'open'
            db.session.commit()
            if action == 'reply' and body and current_app.config.get('MAIL_SERVER') and current_app.config.get('MAIL_DEFAULT_SENDER'):
                try:
                    mail.send(Message(
                        subject=f'Reply from TrainingLows support: {thread.subject}',
                        recipients=[thread.requester_email],
                        sender=current_app.config.get('MAIL_DEFAULT_SENDER'),
                        body=f'There is a new reply in your TrainingLows support discussion "{thread.subject}".\n\n{body}\n\nOpen Support TL to continue the conversation.',
                    ))
                except Exception:
                    current_app.logger.exception('Could not send support reply notification')
            return redirect(url_for('.thread', thread_id=thread.id))
        return self.render('admin/support/thread.html', thread=thread)


class AdminHomeView(AdminAccessMixin, AdminIndexView):
    @expose('/')
    def index(self):
        models = [
            User, Athlete, Coach, Activity, PlannedActivity, DailyMetric,
            TrainingSeason, TrainingObjective, TrainingPhase, PhaseObjective,
            PhaseWeeklyTarget, PendingInvite, StravaToken, StravaActivity, SupportThread, SupportMessage,
        ]
        counts = []
        for model in models:
            try:
                counts.append({'label': model.__name__, 'count': model.query.count(), 'endpoint': self._endpoint_for(model)})
            except Exception:
                counts.append({'label': model.__name__, 'count': '—', 'endpoint': None})
        counts.sort(key=lambda item: item['label'].lower())
        return self.render('admin/index.html', counts=counts, activity_types=list(ACTIVITY_TYPES), admin_email=ADMIN_EMAIL)

    def _endpoint_for(self, model):
        view = self._admin_view_for_model(model)
        return view.endpoint if view else None

    def _admin_view_for_model(self, model):
        return next((view for view in self.admin._views if getattr(view, 'model', None) is model), None)


def init_admin(app):
    admin = app.extensions.get('traininglows_admin')
    if admin is not None:
        return admin

    admin = Admin(
        app,
        name='TrainingLows Admin',
        index_view=AdminHomeView(name='Overview', url='/admin'),
        template_mode='bootstrap4',
    )
    app.extensions['traininglows_admin'] = admin

    views = [
        (User, UserAdminView, 'Accounts'),
        (Athlete, AthleteAdminView, 'People'),
        (Coach, CoachAdminView, 'People'),
        (Activity, ActivityAdminView, 'Training'),
        (PlannedActivity, AdminModelView, 'Training'),
        (DailyMetric, AdminModelView, 'Recovery'),
        (TrainingSeason, AdminModelView, 'Planning'),
        (TrainingObjective, AdminModelView, 'Planning'),
        (TrainingPhase, AdminModelView, 'Planning'),
        (PhaseObjective, AdminModelView, 'Planning'),
        (PhaseWeeklyTarget, AdminModelView, 'Planning'),
        (PendingInvite, AdminModelView, 'Connections'),
        (StravaToken, AdminModelView, 'Strava'),
        (StravaActivity, AdminModelView, 'Strava'),
    ]
    for model, view_class, category in views:
        admin.add_view(view_class(model, db.session, category=category))
    admin.add_view(SupportAdminView(name='Support inbox', endpoint='support', category='Support'))

    for activity_type in ACTIVITY_TYPES:
        activity_model = get_activity_model(activity_type)
        if activity_model is not Activity and not any(getattr(view, 'model', None) is activity_model for view in admin._views):
            admin.add_view(ActivityAdminView(activity_model, db.session, name=activity_type.title(), category='Activities'))
    return admin
