"""Build the Docker Compose runtime env file from GitHub Environment values.

Only the temporary destination path is an argument; secret values come from the
process environment and are never printed. Do not upload the generated file.
"""

import argparse
import ipaddress
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


class InvalidConfig(ValueError):
    pass


def single_line(name, value, limit=256):
    if len(value) > limit or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise InvalidConfig(f'{name} must be a single line within its size limit')
    if value != value.strip():
        raise InvalidConfig(f'{name} must not have leading or trailing whitespace')
    return value


def validate_origin(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise InvalidConfig('LEADS_ALLOWED_ORIGINS contains an invalid origin') from None
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path or parsed.query or parsed.fragment
            or (port is not None and not 1 <= port <= 65535)):
        raise InvalidConfig('LEADS_ALLOWED_ORIGINS must contain exact http(s) origins without paths')
    host = parsed.hostname
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', host):
            raise InvalidConfig('LEADS_ALLOWED_ORIGINS contains an invalid hostname') from None
        if any(not label or len(label) > 63 or label.startswith('-') or label.endswith('-')
               for label in host.split('.')):
            raise InvalidConfig('LEADS_ALLOWED_ORIGINS contains an invalid hostname')
    return value


def runtime_values(environment):
    enabled = environment.get('LEADS_ENABLED', '').strip().lower() or 'false'
    if enabled not in ('true', 'false'):
        raise InvalidConfig('LEADS_ENABLED must be true or false')
    token = single_line('TELEGRAM_BOT_TOKEN', environment.get('TELEGRAM_BOT_TOKEN', ''), 160)
    if token and not re.fullmatch(r'[0-9]{5,20}:[A-Za-z0-9_-]{20,128}', token):
        raise InvalidConfig('TELEGRAM_BOT_TOKEN has an invalid format')
    password = single_line('TELEGRAM_ADMIN_PASSWORD',
                           environment.get('TELEGRAM_ADMIN_PASSWORD', '') or '12345678')
    if "'" in password or '\\' in password:
        raise InvalidConfig('TELEGRAM_ADMIN_PASSWORD must not contain apostrophes or backslashes')
    retry = environment.get('TELEGRAM_RETRY_SECONDS', '').strip() or '300'
    if not re.fullmatch(r'[0-9]{1,8}', retry) or not 300 <= int(retry) <= 86400:
        raise InvalidConfig('TELEGRAM_RETRY_SECONDS must be an integer from 300 to 86400')
    raw_origins = single_line('LEADS_ALLOWED_ORIGINS',
                             environment.get('LEADS_ALLOWED_ORIGINS', ''), 4096)
    origins = []
    for value in raw_origins.split(',') if raw_origins else []:
        value = value.strip()
        validate_origin(value)
        if value not in origins:
            origins.append(value)
    if enabled == 'true' and (not token or not origins):
        raise InvalidConfig('Enabled leads require TELEGRAM_BOT_TOKEN and LEADS_ALLOWED_ORIGINS')
    return {
        'LEADS_ENABLED': enabled,
        'TELEGRAM_BOT_TOKEN': token,
        'TELEGRAM_ADMIN_PASSWORD': password,
        'TELEGRAM_RETRY_SECONDS': str(int(retry)),
        'LEADS_ALLOWED_ORIGINS': ','.join(origins),
    }


def compose_env(values):
    # Single quotes preserve dollar signs and punctuation across Compose versions.
    # Validation excludes characters that older Compose cannot quote reliably.
    return ''.join(f"{key}='{value}'\n"
                   for key, value in values.items())


def write_config(destination, environment):
    text = compose_env(runtime_values(environment))
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(text)
    except BaseException:
        Path(destination).unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('destination')
    arguments = parser.parse_args()
    try:
        write_config(arguments.destination, os.environ)
    except (InvalidConfig, OSError) as error:
        # OSError might include a path, but never includes config values.
        print(f'Runtime configuration error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
