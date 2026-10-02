"""Shared transactional email helpers.

Delivery strategy, in order:
1. Brevo HTTP API (when BREVO_API_KEY is set) — honest delivery feedback,
   works on hosts that block SMTP ports.
2. SMTP via Flask-Mail (when MAIL_SERVER is configured) — fine for local dev.
3. Dev fallback — no transport configured; surfaces the action URL via flash
   so local development keeps working without any mail account.

Always send both a plain-text and an HTML body: HTML-only email is a spam
signal, and text-only email with raw URLs also scores poorly.
"""

import html
import os
import re
import socket

import requests
from flask import current_app, flash
from flask_mail import Mail, Message

from app import mail

# Result of a send attempt.
SENT = 'sent'                      # a provider accepted the message
FALLBACK_QUEUED = 'fallback-queued'  # accepted by an old Gmail-linked account; delivery unverifiable
FAILED = 'failed'                  # nothing accepted the message

BREVO_API_URL = 'https://api.brevo.com/v3/smtp/email'

# Old Gmail addresses that were used as sender while authenticating with a
# different account. Gmail rewrites the From header in that setup, which fails
# SPF/DMARC alignment at strict providers (e.g. netplus.ch silently drops it).
STALE_GMAIL_SENDERS = {
    'astorimattia05@gmail.com',
}

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def is_valid_email(address):
    return bool(address) and bool(_EMAIL_RE.match(address))


def _is_valid_email(address):
    return is_valid_email(address)


def _brevo_sender_address():
    """Sender address used for the Brevo API.

    Gmail addresses used while authenticating with a different Gmail account
    are known to be dropped downstream, so we warn loudly and send through
    Brevo anyway (Brevo rewrites unverified senders to its own domain).
    """
    sender = (current_app.config.get('MAIL_DEFAULT_SENDER') or '').strip()
    if sender.lower() in STALE_GMAIL_SENDERS:
        current_app.logger.warning(
            'MAIL_DEFAULT_SENDER=%s is a stale Gmail address from the old account; '
            'mail will be sent through Brevo instead to avoid silent drops.',
            sender,
        )
    return sender


def _send_via_brevo(subject, text_body, html_body, recipients, reply_to=None, sender=None):
    api_key = (current_app.config.get('BREVO_API_KEY') or '').strip()
    if not api_key:
        return None

    sender_address = sender or _brevo_sender_address()
    sender_name = (current_app.config.get('MAIL_SENDER_NAME') or _app_name()).strip()
    payload = {
        'sender': {'name': sender_name, 'email': sender_address},
        'to': [{'email': address} for address in recipients],
        'subject': subject,
        'textContent': text_body,
        'htmlContent': html_body,
    }
    if reply_to and _is_valid_email(reply_to):
        payload['replyTo'] = {'email': reply_to}

    try:
        response = requests.post(
            BREVO_API_URL,
            json=payload,
            headers={'api-key': api_key, 'accept': 'application/json'},
            timeout=10,
        )
    except requests.RequestException:
        current_app.logger.exception('Brevo API request failed for subject %r', subject)
        return FAILED

    if 200 <= response.status_code < 300:
        return SENT

    current_app.logger.error(
        'Brevo API rejected email %r: HTTP %s %s',
        subject, response.status_code, response.text[:500],
    )
    return FAILED


def _send_via_smtp(subject, text_body, html_body, recipients, reply_to=None, sender=None):
    if not current_app.config.get('MAIL_SERVER'):
        return None

    sender = sender or (current_app.config.get('MAIL_DEFAULT_SENDER') or '').strip()
    if not sender:
        return None

    # Pick credentials based on sender address
    credentials = current_app.config.get('MAIL_CREDENTIALS', {})
    service_creds = credentials.get('service', {})
    support_creds = credentials.get('support', {})
    
    username = None
    password = None
    if sender == service_creds.get('sender'):
        username = service_creds.get('username')
        password = service_creds.get('password')
    elif sender == support_creds.get('sender'):
        username = support_creds.get('username')
        password = support_creds.get('password')
    
    # Fallback to legacy single-account config if no specific credentials found
    if not username:
        username = current_app.config.get('MAIL_USERNAME', '')
        password = current_app.config.get('MAIL_PASSWORD', '')

    message = Message(
        subject=subject,
        recipients=list(recipients),
        sender=sender,
        body=text_body,
        html=html_body,
    )
    if reply_to and _is_valid_email(reply_to):
        message.reply_to = reply_to

    try:
        # Use smtplib directly for thread-safe per-message credentials
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = sender
        msg['To'] = ', '.join(recipients)
        if reply_to:
            msg['Reply-To'] = reply_to
        
        msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))
        
        server = current_app.config.get('MAIL_SERVER')
        port = current_app.config.get('MAIL_PORT', 587)
        use_tls = current_app.config.get('MAIL_USE_TLS', True)
        
        with smtplib.SMTP(server, port, timeout=10) as smtp:
            if use_tls:
                smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        current_app.logger.error(
            'SMTP authentication failed for %r: %s. Username=%s Server=%s:%s',
            subject, e, username, server, port,
        )
        return FAILED
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, socket.timeout) as e:
        current_app.logger.error(
            'SMTP connection failed for %r: %s. Server=%s:%s',
            subject, e, server, port,
        )
        return FAILED
    except Exception as e:
        current_app.logger.exception('SMTP send failed for subject %r: %s', subject, e)
        return FAILED

    # The old Gmail setup accepts mail but downstream providers may drop it.
    if sender.lower() in STALE_GMAIL_SENDERS:
        return FALLBACK_QUEUED
    return SENT


def send_email(subject, text_body, html_body, recipients, reply_to=None,
               dev_fallback_url=None, sender=None):
    """Send a transactional email. Returns SENT / FALLBACK_QUEUED / FAILED.

    When no transport is configured at all (typical local dev), the action URL
    is flashed so the flow can still be completed, and SENT is returned.

    The `sender` parameter overrides MAIL_DEFAULT_SENDER for this message only.
    """
    recipients = [address for address in recipients if _is_valid_email(address)]
    if not recipients:
        current_app.logger.error('No valid recipients for email %r', subject)
        return FAILED

    current_app.logger.info(
        'Attempting to send email %r to %s from %s',
        subject, recipients, sender or current_app.config.get('MAIL_DEFAULT_SENDER'),
    )

    brevo_result = _send_via_brevo(subject, text_body, html_body, recipients, reply_to, sender=sender)
    if brevo_result == SENT:
        current_app.logger.info('Email %r sent via Brevo', subject)
        return SENT
    if brevo_result == FAILED:
        current_app.logger.warning('Brevo send failed for %r, trying SMTP fallback', subject)

    smtp_result = _send_via_smtp(subject, text_body, html_body, recipients, reply_to, sender=sender)
    if smtp_result == SENT:
        current_app.logger.info('Email %r sent via SMTP', subject)
        return smtp_result
    if smtp_result == FALLBACK_QUEUED:
        current_app.logger.warning('Email %r queued via SMTP (unverified sender)', subject)
        return smtp_result
    if smtp_result == FAILED:
        current_app.logger.error('SMTP send failed for %r', subject)

    if brevo_result == FAILED or smtp_result == FAILED:
        return FAILED

    if os.getenv('APP_ENV', '').strip().lower() == 'production':
        # Fail closed: a production deploy without a mail transport must never
        # leak action URLs (verification links) into the browser.
        current_app.logger.error(
            'No email transport configured in production; dropping email %r to %s. '
            'MAIL_SERVER=%s BREVO_API_KEY=%s',
            subject, recipients,
            bool(current_app.config.get('MAIL_SERVER')),
            bool(current_app.config.get('BREVO_API_KEY')),
        )
        return FAILED

    # No transport configured: dev mode.
    current_app.logger.info(
        'No email transport configured; email %r to %s was not sent.',
        subject, recipients,
    )
    if dev_fallback_url:
        flash(f'Dev mode — open this link directly: {dev_fallback_url}', 'info')
    return SENT


def email_layout(title, content_html):
    """Consistent, spam-score-friendly HTML wrapper for all emails."""
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"></head>'
        '<body style="margin:0;padding:0;background:#f5f5f5;'
        'font-family:Arial,Helvetica,sans-serif;">'
        '<div style="max-width:560px;margin:0 auto;padding:24px;">'
        '<div style="background:#ffffff;border-radius:12px;padding:32px;'
        'border:1px solid #e5e5e5;">'
        f'<h1 style="margin:0 0 16px;font-size:20px;color:#111;">{title}</h1>'
        f'{content_html}'
        '<p style="margin:24px 0 0;font-size:12px;color:#888;">'
        f'{_esc(_app_name())} &mdash; training load management'
        '</p></div></div></body></html>'
    )


def _esc(value):
    return html.escape(value or '')


def _app_name():
    return current_app.config.get('APP_NAME') or 'TrainingLows'


def _short_app_name():
    return current_app.config.get('SHORT_APP_NAME') or 'TL'


def _button(url, label):
    return (
        f'<a href="{_esc(url)}" style="display:inline-block;margin:16px 0;'
        'padding:12px 24px;background:#111;color:#fff;text-decoration:none;'
        f'border-radius:8px;font-size:15px;">{_esc(label)}</a>'
    )


def _fallback_link(url):
    return (
        '<p style="font-size:13px;color:#555;">If the button does not work, '
        f'open this link in your browser:<br><a href="{_esc(url)}" '
        f'style="color:#111;word-break:break-all;">{_esc(url)}</a></p>'
    )


def build_verification_email(first_name, verification_url):
    """Returns (subject, text_body, html_body)."""
    app_name = _app_name()
    subject = f'Verify your {app_name} email address'
    text_body = (
        f'Hi {first_name},\n\n'
        f'Please verify your email address by opening this link:\n{verification_url}\n\n'
        'The link is valid for 7 days.\n\n'
        'If you did not request this, you can ignore this email.'
    )
    html_body = email_layout(
        'Verify your email address',
        f'<p style="font-size:15px;color:#333;">Hi {_esc(first_name)},</p>'
        '<p style="font-size:15px;color:#333;">Please confirm that this email '
        f'address belongs to you to activate your {_esc(app_name)} account.</p>'
        f'{_button(verification_url, "Verify email address")}'
        f'{_fallback_link(verification_url)}'
        '<p style="font-size:13px;color:#555;">The link is valid for 7 days. '
        'If you did not request this, you can ignore this email.</p>',
    )
    return subject, text_body, html_body


def build_invitation_email(recipient_name, sender_name, invite_url, invitation_type):
    """Returns (subject, text_body, html_body)."""
    app_name = _app_name()
    subject = f'{sender_name} invited you to connect on {app_name}'
    text_body = (
        f'Hi {recipient_name},\n\n'
        f'{sender_name} sent you a {invitation_type} invitation on {app_name}.\n\n'
        f'Open the invitation here:\n{invite_url}\n\n'
        'You will need to sign in to review and accept or decline it.\n\n'
        'If you were not expecting this invitation, you can ignore this email.'
    )
    html_body = email_layout(
        f'New invitation on {_esc(app_name)}',
        f'<p style="font-size:15px;color:#333;">Hi {_esc(recipient_name)},</p>'
        f'<p style="font-size:15px;color:#333;">{_esc(sender_name)} sent you a '
        f'{_esc(invitation_type)} invitation on {_esc(app_name)}.</p>'
        f'{_button(invite_url, "Review invitation")}'
        f'{_fallback_link(invite_url)}'
        '<p style="font-size:13px;color:#555;">You will need to sign in to '
        'accept or decline it. If you were not expecting this invitation, '
        'you can ignore this email.</p>',
    )
    return subject, text_body, html_body


def build_support_request_email(requester, subject_line, message_body):
    """Returns (subject, text_body, html_body)."""
    subject = f'{_app_name()} support: {subject_line}'
    text_body = f'From: {requester}\n\n{message_body}'
    html_body = email_layout(
        f'Support request: {_esc(subject_line)}',
        f'<p style="font-size:13px;color:#555;">From: {_esc(requester)}</p>'
        f'<p style="font-size:15px;color:#333;white-space:pre-line;">{_esc(message_body)}</p>',
    )
    return subject, text_body, html_body


def build_support_reply_email(thread_subject, reply_body):
    """Returns (subject, text_body, html_body)."""
    app_name = _app_name()
    short_app_name = _short_app_name()
    subject = f'Reply from {app_name} support: {thread_subject}'
    text_body = (
        f'There is a new reply in your {app_name} support discussion "{thread_subject}".'
        f'\n\n{reply_body}\n\nOpen Support {short_app_name} to continue the conversation.'
    )
    html_body = email_layout(
        f'New reply: {_esc(thread_subject)}',
        '<p style="font-size:15px;color:#333;">There is a new reply in your '
        f'{_esc(app_name)} support discussion &quot;{_esc(thread_subject)}&quot;.</p>'
        f'<p style="font-size:15px;color:#333;white-space:pre-line;">{_esc(reply_body)}</p>'
        f'<p style="font-size:13px;color:#555;">Open Support {_esc(short_app_name)} to continue '
        'the conversation.</p>',
    )
    return subject, text_body, html_body


def build_bug_report_email(reporter, title, page_area, severity, steps, expected, actual):
    """Returns (subject, text_body, html_body)."""
    safe_title = ' '.join(title.split())
    subject = f'{_app_name()} bug report [{severity}]: {safe_title}'
    text_body = (
        f'From: {reporter}\n'
        f'Severity: {severity}\n'
        f'Where: {page_area}\n\n'
        f'Steps to reproduce:\n{steps}\n\n'
        f'Expected result:\n{expected}\n\n'
        f'Actual result:\n{actual}'
    )

    def block(heading, body):
        return (
            f'<p style="margin:16px 0 4px;font-size:13px;font-weight:bold;color:#555;">{heading}</p>'
            f'<p style="margin:0;font-size:15px;color:#333;white-space:pre-line;">{_esc(body)}</p>'
        )

    html_body = email_layout(
        f'Bug report: {_esc(safe_title)}',
        f'<p style="font-size:13px;color:#555;">From: {_esc(reporter)} &middot; '
        f'Severity: {_esc(severity)} &middot; Where: {_esc(page_area)}</p>'
        + block('Steps to reproduce', steps)
        + block('Expected result', expected)
        + block('Actual result', actual),
    )
    return subject, text_body, html_body
