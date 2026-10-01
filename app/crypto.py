"""Symmetric encryption for sensitive values stored in the database.

Used for Strava OAuth tokens at rest. The Fernet key is derived from
SECRET_KEY, so rotating SECRET_KEY invalidates previously stored ciphertext
(affected users simply reconnect Strava).
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

_KEY_INFO = 'traininglows-token-v1'


class TokenDecryptionError(Exception):
    """Raised when a stored value cannot be decrypted with the current key."""


def _fernet():
    secret = current_app.config['SECRET_KEY']
    digest = hashlib.sha256(f'{secret}|{_KEY_INFO}'.encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_value(value: str) -> str:
    """Encrypt a short string for storage in a database column."""
    return _fernet().encrypt(value.encode('utf-8')).decode('ascii')


def decrypt_value(value: str) -> str:
    """Decrypt a value produced by encrypt_value. Raises TokenDecryptionError."""
    try:
        return _fernet().decrypt(value.encode('ascii')).decode('utf-8')
    except (InvalidToken, ValueError) as error:
        raise TokenDecryptionError(
            'Stored token could not be decrypted; reconnect the external account.'
        ) from error
