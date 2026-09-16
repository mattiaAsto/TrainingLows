from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail
from flask_login import UserMixin, LoginManager, login_user, current_user
from flask_caching import Cache
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from itsdangerous import URLSafeTimedSerializer
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from distutils.util import strtobool
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
#from app.admin.routes import AdminHomeView
import atexit
import os
from pathlib import Path
from sqlalchemy import inspect, text


db = SQLAlchemy()
mail = Mail()
login_manager = LoginManager()
cache = Cache()
#admin_panel = Admin(name='FantaCO Admin', template_mode='bootstrap3', index_view=AdminHomeView())


def create_app():

    app=Flask(__name__)

    @app.template_filter('date_eu')
    def format_date_european(value, include_time=False):
        if value is None:
            return ''
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace('Z', '+00:00'))
            except ValueError:
                return value
        if include_time and isinstance(value, datetime):
            return value.strftime('%d.%m.%Y %H:%M')
        return value.strftime('%d.%m.%Y')

    # Recovering variables from .env file
    load_dotenv()

    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    db_hostname = os.getenv("DB_HOSTNAME")
    db_port = os.getenv("DB_PORT")
    db_name = os.getenv("DB_NAME")

    db_complete_url = os.getenv("DB_COMPLETE_URL", None)

    if not db_complete_url:
        db_complete_url = f'mysql+pymysql://{db_user}:{db_password}@{db_hostname}:3306/{db_name}'

    mail_server = str(os.getenv("MAIL_SERVER"))
    mail_port = int(os.getenv("MAIL_PORT"))
    mail_use_tls = True
    mail_use_ssl = False
    mail_username = str(os.getenv("MAIL_USERNAME"))
    mail_password = str(os.getenv("MAIL_PASSWORD"))
    mail_default_sender = str(os.getenv("MAIL_DEFAULT_SENDER"))

    secret_key = os.getenv("SECRET_KEY")

    cache_type = os.getenv("CACHE_TYPE")
    cache_default_timeout = int(os.getenv("CACHE_DEFAULT_TIMEOUT"))


    # Sqalchemy configs --> pakage used to interact with an sql database (mysql in local)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_complete_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_POOL_SIZE'] = 10
    app.config['SQLALCHEMY_POOL_TIMEOUT'] = 5  
    app.config['SQLALCHEMY_POOL_RECYCLE'] = 3600 

    # Flask-Mail configs
    app.config['MAIL_SERVER'] = mail_server   # Server SMTP (es. Gmail: smtp.gmail.com)
    app.config['MAIL_PORT'] = mail_port                    # Porta del server SMTP (587 per TLS, 465 per SSL)
    app.config['MAIL_USE_TLS'] = mail_use_tls               # Utilizzare TLS (True/False)
    app.config['MAIL_USE_SSL'] = mail_use_ssl               # Utilizzare SSL (True/False)
    app.config['MAIL_USERNAME'] = mail_username  # Email per l'autenticazione
    app.config['MAIL_PASSWORD'] = mail_password         # Password per l'autenticazione
    app.config['MAIL_DEFAULT_SENDER'] = mail_default_sender  # Mittente predefinito (opzionale)

    # Secret key for Flask security config
    app.config['SECRET_KEY'] = secret_key

    app.url_serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

    # Caching config
    app.config['CACHE_TYPE'] = cache_type
    app.config['CACHE_DEFAULT_TIMEOUT'] = cache_default_timeout

    # Confing strava 
    app.config['STRAVA_CLIENT_ID']     = os.getenv("STRAVA_CLIENT_ID")
    app.config['STRAVA_CLIENT_SECRET'] = os.getenv("STRAVA_CLIENT_SECRET")
    app.config['STRAVA_REDIRECT_URI']  = os.getenv("STRAVA_REDIRECT_URI")
    app.config['STRAVA_SCOPES']        = os.getenv("STRAVA_SCOPES", "read,activity:read")
    app.config['STRAVA_WEBHOOK_VERIFY_TOKEN'] = os.getenv('STRAVA_WEBHOOK_VERIFY_TOKEN', '')
    app.config['STRAVA_SYNC_ENABLED'] = os.getenv('STRAVA_SYNC_ENABLED', '1') == '1'
    app.config['PREFERRED_URL_SCHEME'] = os.getenv('PREFERRED_URL_SCHEME', 'http')

    #init Flask-Mail
    mail.init_app(app)

    #init SQLAlchemy 
    db.init_app(app)

    #init Flask-Login
    login_manager.init_app(app)

    #init Flask-Cache
    cache.init_app(app)

    #init admin panel feature
    #admin_panel.init_app(app)

    # Import tables as classes from the models.py file
    #from app.admin.routes import UserOnlyView, AdminOnlyView, RunnerOnlyView, ArticleView, RunnerPointsView, UserRunnerView, LeagueView, LeagueDataView, UserLeagueView, TMOView
    from .models import User

    with app.app_context():
        try:
            db.create_all()
            users_columns = {column['name'] for column in inspect(db.engine).get_columns('Users')}
            if 'strava_auto_update' not in users_columns:
                db.session.execute(text("ALTER TABLE Users ADD COLUMN strava_auto_update BOOLEAN NOT NULL DEFAULT 0"))
                db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception('Could not initialize the Strava sync schema')


    

    """ Adding the tables to the admin panel
    admin_panel.add_view(ArticleView(Article, db.session))
    admin_panel.add_view(UserOnlyView(User, db.session))
    admin_panel.add_view(RunnerOnlyView(Runner, db.session))
    admin_panel.add_view(RunnerPointsView(RunnerPoints, db.session))
    admin_panel.add_view(UserRunnerView(UserRunner, db.session))
    admin_panel.add_view(LeagueView(League, db.session))
    admin_panel.add_view(LeagueDataView(LeagueData, db.session))
    admin_panel.add_view(UserLeagueView(UserLeague, db.session))
    admin_panel.add_view(TMOView(TMO, db.session))"""


    # Register blueprints
    from app.main import main as main_blueprint
    from app.auth import auth as auth_blueprint
    from app.strava import strava as strava_blueprint
    from app.planner import planner as planner_blueprint
    from app.season import season as season_blueprint
    from app.settings import settings as settings_blueprint
    from app.about import about as about_blueprint
    app.register_blueprint(main_blueprint, url_prefix='/')
    app.register_blueprint(auth_blueprint, url_prefix='/auth')
    app.register_blueprint(strava_blueprint, url_prefix='/strava')
    app.register_blueprint(planner_blueprint, url_prefix='/planner')
    app.register_blueprint(season_blueprint, url_prefix='/season')
    app.register_blueprint(settings_blueprint, url_prefix='/settings')
    app.register_blueprint(about_blueprint, url_prefix='/about')

    if app.config['STRAVA_SYNC_ENABLED']:
        from app.strava.routes import sync_all_strava_users
        scheduler = BackgroundScheduler(daemon=True)
        scheduler.add_job(
            lambda: sync_all_strava_users(app),
            trigger='interval',
            hours=6,
            id='strava-fallback-sync',
            replace_existing=True,
        )
        scheduler.start()
        app.extensions['strava_scheduler'] = scheduler
        atexit.register(lambda: scheduler.shutdown(wait=False))


    # Database creation is intentionally handled from run.py so Flask's debug reloader
    # does not trigger concurrent DDL on MySQL when the app restarts in development.
    login_manager.login_view="auth.login"

    # Structure needed to use "current_user"
    from .models import User
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(user_id)
    
    
    
    # Create error handling instances

    @app.errorhandler(500)
    def page_not_found(error):
        error ={
            "title": "500 internal error",
            "code": 500,
            "message": "Sembra che ci sia stato un errore interno al server, ricarica la pagina o riprova piu tardi a raggiungere la pagina richiesta.",
            "image": "internal",
        }
        return render_template("error.html", error=error), 500
    
    @app.errorhandler(405)
    def page_not_found(error):
        error ={
            "title": "405 bad request",
            "code": 405,
            "message": "Opss..., sembra che la richiesta invata non sia gestibile dal server",
            "image": "lost",
        }
        return render_template("error.html", error=error), 405
    
    @app.errorhandler(404)
    def page_not_found(error):
        error = {
            "title": "404 not found",
            "code": 404,
            "message": "Opss.. Sembra che ti sei perso. La pagina che stai cercando non è qui.",
            "image": "lost",
        }
        return render_template("error.html", error=error), 404
    
    @app.errorhandler(403)
    def page_not_found(error):
        error ={
            "title": "403 error",
            "code": 403,
            "message": "Opss.. Sembra che tu non abbia le autorizzazioni necessarie ad accedere a questa pagina, nel caso di bisogno contatta l'assistenza.",
            "image": "auth_error",
        }
        return render_template("error.html", error=error), 403
    
    
        



    return app