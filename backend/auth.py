"""Bounded password hashing for the shared Telegram administrator password."""
import hashlib
import hmac
import re
import secrets

from backend.bot_ui import BUTTON_COMMANDS


_ITERATIONS = 600_000
_ENCODED = re.compile(r'pbkdf2_sha256\$600000\$([0-9a-f]{32})\$([0-9a-f]{64})')


def validate_password(candidate: str) -> str | None:
    """Return a user-facing error; passwords are never silently trimmed."""
    if not isinstance(candidate, str) or not 12 <= len(candidate) <= 128:
        return 'Пароль должен содержать от 12 до 128 символов.'
    if candidate != candidate.strip():
        return 'Пароль не должен начинаться или заканчиваться пробелами.'
    if candidate.startswith('/') or candidate in BUTTON_COMMANDS:
        return 'Пароль не должен начинаться с / или совпадать с названием кнопки меню.'
    try:
        candidate.encode('utf-8')
    except UnicodeError:
        return 'Пароль содержит недопустимые символы.'
    return None


def hash_password(candidate: str) -> str:
    error = validate_password(candidate)
    if error:
        raise ValueError(error)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', candidate.encode('utf-8'), salt, _ITERATIONS, dklen=32)
    return f'pbkdf2_sha256${_ITERATIONS}${salt.hex()}${digest.hex()}'


def verify_password(candidate: str, encoded: str) -> bool:
    # Reject unknown work factors and malformed lengths before doing any work.
    # The database cannot request unbounded CPU/memory through a crafted hash.
    if validate_password(candidate) or not isinstance(encoded, str) or len(encoded) > 160:
        return False
    match = _ENCODED.fullmatch(encoded)
    if not match:
        return False
    salt, expected = (bytes.fromhex(value) for value in match.groups())
    actual = hashlib.pbkdf2_hmac('sha256', candidate.encode('utf-8'), salt, _ITERATIONS, dklen=32)
    return hmac.compare_digest(actual, expected)
