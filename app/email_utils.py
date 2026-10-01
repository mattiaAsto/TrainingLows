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

import requests
from flask import current_app, flash
from flask_mail import Message

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


def _send_via_brevo(subject, text_body, html_body, recipients, reply_to=None):
    api_key = (current_app.config.get('BREVO_API_KEY') or '').strip()
    if not api_key:
        return None

    sender_address = _brevo_sender_address()
    sender_name = (current_app.config.get('MAIL_SENDER_NAME') or 'TrainingLows').strip()
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


def _send_via_smtp(subject, text_body, html_body, recipients, reply_to=None):
    if not current_app.config.get('MAIL_SERVER'):
        return None

    sender = (current_app.config.get('MAIL_DEFAULT_SENDER') or '').strip()
    if not sender:
        return None

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
        mail.send(message)
    except Exception:
        current_app.logger.exception('SMTP send failed for subject %r', subject)
        return FAILED

    # The old Gmail setup accepts mail but downstream providers may drop it.
    if sender.lower() in STALE_GMAIL_SENDERS:
        return FALLBACK_QUEUED
    return SENT


def send_email(subject, text_body, html_body, recipients, reply_to=None,
               dev_fallback_url=None):
    """Send a transactional email. Returns SENT / FALLBACK_QUEUED / FAILED.

    When no transport is configured at all (typical local dev), the action URL
    is flashed so the flow can still be completed, and SENT is returned.
    """
    recipients = [address for address in recipients if _is_valid_email(address)]
    if not recipients:
        current_app.logger.error('No valid recipients for email %r', subject)
        return FAILED

    brevo_result = _send_via_brevo(subject, text_body, html_body, recipients, reply_to)
    if brevo_result == SENT:
        return SENT

    smtp_result = _send_via_smtp(subject, text_body, html_body, recipients, reply_to)
    if smtp_result is not None:
        return smtp_result

    if brevo_result == FAILED:
        return FAILED

    if os.getenv('APP_ENV', '').strip().lower() == 'production':
        # Fail closed: a production deploy without a mail transport must never
        # leak action URLs (verification links) into the browser.
        current_app.logger.error(
            'No email transport configured in production; dropping email %r to %s.',
            subject, recipients,
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
        'TrainingLows &mdash; training load management'
        '</p></div></div></body></html>'
    )


def _esc(value):
    return html.escape(value or '')


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
    subject = 'Verify your TrainingLows email address'
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
        'address belongs to you to activate your TrainingLows account.</p>'
        f'{_button(verification_url, "Verify email address")}'
        f'{_fallback_link(verification_url)}'
        '<p style="font-size:13px;color:#555;">The link is valid for 7 days. '
        'If you did not request this, you can ignore this email.</p>',
    )
    return subject, text_body, html_body


def build_invitation_email(recipient_name, sender_name, invite_url, invitation_type):
    """Returns (subject, text_body, html_body)."""
    subject = f'{sender_name} invited you to connect on TrainingLows'
    text_body = (
        f'Hi {recipient_name},\n\n'
        f'{sender_name} sent you a {invitation_type} invitation on TrainingLows.\n\n'
        f'Open the invitation here:\n{invite_url}\n\n'
        'You will need to sign in to review and accept or decline it.\n\n'
        'If you were not expecting this invitation, you can ignore this email.'
    )
    html_body = email_layout(
        'New invitation on TrainingLows',
        f'<p style="font-size:15px;color:#333;">Hi {_esc(recipient_name)},</p>'
        f'<p style="font-size:15px;color:#333;">{_esc(sender_name)} sent you a '
        f'{_esc(invitation_type)} invitation on TrainingLows.</p>'
        f'{_button(invite_url, "Review invitation")}'
        f'{_fallback_link(invite_url)}'
        '<p style="font-size:13px;color:#555;">You will need to sign in to '
        'accept or decline it. If you were not expecting this invitation, '
        'you can ignore this email.</p>',
    )
    return subject, text_body, html_body


def build_support_request_email(requester, subject_line, message_body):
    """Returns (subject, text_body, html_body)."""
    subject = f'TrainingLows support: {subject_line}'
    text_body = f'From: {requester}\n\n{message_body}'
    html_body = email_layout(
        f'Support request: {_esc(subject_line)}',
        f'<p style="font-size:13px;color:#555;">From: {_esc(requester)}</p>'
        f'<p style="font-size:15px;color:#333;white-space:pre-line;">{_esc(message_body)}</p>',
    )
    return subject, text_body, html_body


def build_support_reply_email(thread_subject, reply_body):
    """Returns (subject, text_body, html_body)."""
    subject = f'Reply from TrainingLows support: {thread_subject}'
    text_body = (
        f'There is a new reply in your TrainingLows support discussion "{thread_subject}".'
        f'\n\n{reply_body}\n\nOpen Support TL to continue the conversation.'
    )
    html_body = email_layout(
        f'New reply: {_esc(thread_subject)}',
        '<p style="font-size:15px;color:#333;">There is a new reply in your '
        f'TrainingLows support discussion &quot;{_esc(thread_subject)}&quot;.</p>'
        f'<p style="font-size:15px;color:#333;white-space:pre-line;">{_esc(reply_body)}</p>'
        '<p style="font-size:13px;color:#555;">Open Support TL to continue '
        'the conversation.</p>',
    )
    return subject, text_body, html_body
