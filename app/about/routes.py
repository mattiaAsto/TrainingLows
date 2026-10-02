from datetime import datetime
from zoneinfo import ZoneInfo

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app import db
from app.admin.routes import is_admin_user
from app.email_utils import build_bug_report_email, build_support_request_email, is_valid_email, send_email
from app.models import BugReport, SupportMessage, SupportThread
from app.rate_limit import enforce_rate_limit

from . import about


@about.route('/')
def about_home():
    return render_template('about.html')


@about.route('/buy-me-a-coffee')
def buy_me_a_coffee():
    return render_template(
        'buy_me_a_coffee.html',
        coffee_url=current_app.config.get('BUY_ME_A_COFFEE_URL', ''),
    )


@about.route('/support', methods=['GET', 'POST'])
def support():
    threads = []
    unread_thread_ids = set()
    if current_user.is_authenticated:
        threads = SupportThread.query.filter_by(user_id=current_user.id).order_by(SupportThread.updated_at.desc()).all()
        unread_thread_ids = {
            thread.id for thread in threads
            if any(message.is_admin and (thread.user_last_read_at is None or message.created_at > thread.user_last_read_at) for message in thread.messages)
        }
    if request.method == 'POST':
        enforce_rate_limit('support-request', 6, 3600)
        subject = (request.form.get('subject') or '').strip()[:160]
        message = (request.form.get('message') or '').strip()[:5000]
        sender = current_user.email if current_user.is_authenticated else (request.form.get('email') or '').strip().lower()
        if not current_user.is_authenticated and not is_valid_email(sender):
            flash('Please provide a valid email address.', 'warning')
            return redirect(url_for('about.support'))
        if not subject or not message or not sender:
            flash('Please provide your email, a subject, and a message.', 'warning')
            return redirect(url_for('about.support'))

        thread = SupportThread(
            user_id=current_user.id if current_user.is_authenticated else None,
            requester_email=sender,
            subject=subject,
            status='open',
        )
        db.session.add(thread)
        db.session.flush()
        db.session.add(SupportMessage(
            thread_id=thread.id,
            author_id=current_user.id if current_user.is_authenticated else None,
            author_email=sender,
            body=message,
            is_admin=False,
        ))
        db.session.commit()

        recipient = current_app.config.get('MAIL_SUPPORT_EMAIL')
        if recipient:
            subject_line, text_body, html_body = build_support_request_email(sender, subject, message)
            result = send_email(
                subject_line,
                text_body,
                html_body,
                recipients=[recipient],
                reply_to=sender,
            )
            if result != 'failed':
                flash('Your support request was sent. You can follow the discussion below.', 'success')
            else:
                flash('The support request could not be sent. Please try again later.', 'danger')
        else:
            current_app.logger.info('Support request %s was stored without an email notification.', thread.id)
            flash('Your support request was recorded for review.', 'success')
        return redirect(url_for('about.support'))

    return render_template('support.html', threads=threads, unread_thread_ids=unread_thread_ids)


@about.route('/support/<int:thread_id>', methods=['GET', 'POST'])
def support_thread(thread_id):
    thread = SupportThread.query.get_or_404(thread_id)
    is_admin = is_admin_user()
    if not is_admin and (not current_user.is_authenticated or thread.user_id != current_user.id):
        abort(403)
    if not is_admin and current_user.is_authenticated:
        thread.user_last_read_at = datetime.now(ZoneInfo('Europe/Zurich'))
        db.session.commit()
    if request.method == 'POST':
        body = (request.form.get('message') or '').strip()
        action = request.form.get('action', 'reply')
        if action in {'close', 'reopen'}:
            thread.status = 'closed' if action == 'close' else 'open'
            thread.closed_at = datetime.now(ZoneInfo('Europe/Zurich')) if action == 'close' else None
        elif body:
            db.session.add(SupportMessage(
                thread_id=thread.id,
                author_id=current_user.id if current_user.is_authenticated else None,
                author_email=current_user.email,
                body=body,
                is_admin=is_admin,
            ))
            thread.status = 'open'
        db.session.commit()
        return redirect(url_for('about.support_thread', thread_id=thread.id))
    return render_template('support_thread.html', thread=thread, is_admin=is_admin)


@about.route('/report-bug', methods=['GET', 'POST'])
def report_bug():
    if not current_app.config.get('TESTING_VERSION'):
        abort(404)
    if request.method == 'POST':
        enforce_rate_limit('bug-report', 6, 3600)
        title = (request.form.get('title') or '').strip()[:160]
        page_area = (request.form.get('page_area') or '').strip()[:160]
        steps = (request.form.get('steps_to_reproduce') or '').strip()[:5000]
        expected = (request.form.get('expected_result') or '').strip()[:2000]
        actual = (request.form.get('actual_result') or '').strip()[:2000]
        severity = (request.form.get('severity') or '').strip().lower()
        if severity not in BugReport.SEVERITIES:
            severity = 'minor'
        sender = current_user.email if current_user.is_authenticated else (request.form.get('email') or '').strip().lower()
        if not current_user.is_authenticated and not is_valid_email(sender):
            flash('Please provide a valid email address.', 'warning')
            return redirect(url_for('about.report_bug'))
        if not all([title, page_area, steps, expected, actual, sender]):
            flash('Please fill in every field of the bug report.', 'warning')
            return redirect(url_for('about.report_bug'))

        report = BugReport(
            user_id=current_user.id if current_user.is_authenticated else None,
            reporter_email=sender,
            title=title,
            page_area=page_area,
            steps_to_reproduce=steps,
            expected_result=expected,
            actual_result=actual,
            severity=severity,
            status='new',
        )
        db.session.add(report)
        db.session.commit()

        recipient = current_app.config.get('MAIL_SUPPORT_EMAIL')
        if recipient:
            subject_line, text_body, html_body = build_bug_report_email(sender, title, page_area, severity, steps, expected, actual)
            result = send_email(
                subject_line,
                text_body,
                html_body,
                recipients=[recipient],
                reply_to=sender,
            )
            if result != 'failed':
                flash('Thank you! Your bug report was sent to the team.', 'success')
            else:
                flash('The bug report could not be sent. Please try again later.', 'danger')
        else:
            current_app.logger.info('Bug report %s was stored without an email notification.', report.id)
            flash('Your bug report was recorded for review.', 'success')
        return redirect(url_for('about.report_bug'))

    bug_reports = []
    if current_user.is_authenticated:
        bug_reports = BugReport.query.filter_by(user_id=current_user.id).order_by(BugReport.created_at.desc()).all()
    return render_template('report_bug.html', bug_reports=bug_reports)
