import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


spec = importlib.util.spec_from_file_location(
    'runtime_config', Path(__file__).resolve().parents[1] / 'deploy' / 'runtime_config.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)
TOKEN = '123456789:abcdefghijklmnopqrstuvwxyz_12345678'


class RuntimeConfigTests(unittest.TestCase):
    def test_safe_disabled_defaults(self):
        values = config.runtime_values({})
        self.assertEqual(values['LEADS_ENABLED'], 'false')
        self.assertEqual(values['TELEGRAM_RETRY_SECONDS'], '300')
        self.assertEqual(values['TELEGRAM_ADMIN_PASSWORD'], '12345678')
        self.assertEqual(values['TELEGRAM_BOT_TOKEN'], '')

    def test_enabled_requires_token_and_origin(self):
        for environment in ({'LEADS_ENABLED': 'true'},
                            {'LEADS_ENABLED': 'true', 'TELEGRAM_BOT_TOKEN': TOKEN}):
            with self.assertRaises(config.InvalidConfig):
                config.runtime_values(environment)
        values = config.runtime_values({
            'LEADS_ENABLED': 'true', 'TELEGRAM_BOT_TOKEN': TOKEN,
            'LEADS_ALLOWED_ORIGINS': 'http://129.101.120.192, https://example.com:8443'})
        self.assertEqual(values['LEADS_ALLOWED_ORIGINS'],
                         'http://129.101.120.192,https://example.com:8443')

    def test_invalid_inputs_do_not_leak_values(self):
        inputs = [
            ('LEADS_ENABLED', 'unexpected-private-value'),
            ('TELEGRAM_BOT_TOKEN', 'invalid-private-token'),
            ('TELEGRAM_ADMIN_PASSWORD', 'secret\nINJECTED=value'),
            ('TELEGRAM_ADMIN_PASSWORD', ' secret '),
            ('TELEGRAM_ADMIN_PASSWORD', "quote'private"),
            ('TELEGRAM_ADMIN_PASSWORD', 'slash\\private'),
            ('TELEGRAM_RETRY_SECONDS', '5'),
            ('TELEGRAM_RETRY_SECONDS', '300;echo-private-value'),
            ('LEADS_ALLOWED_ORIGINS', 'https://private.example/path'),
            ('LEADS_ALLOWED_ORIGINS', 'https://user:private@example.com'),
            ('LEADS_ALLOWED_ORIGINS', 'https://private.example?secret=value'),
            ('LEADS_ALLOWED_ORIGINS', 'https://private.example,'),
            ('LEADS_ALLOWED_ORIGINS', 'https://private.example:99999'),
        ]
        for key, value in inputs:
            with self.subTest(key=key):
                with self.assertRaises(config.InvalidConfig) as captured:
                    config.runtime_values({key: value})
                self.assertNotIn(value, str(captured.exception))

    def test_write_is_exclusive_and_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'api.env'
            config.write_config(destination, {'TELEGRAM_BOT_TOKEN': TOKEN})
            self.assertIn(TOKEN, destination.read_text(encoding='utf-8'))
            if os.name != 'nt':
                self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                config.write_config(destination, {})
            self.assertIn(TOKEN, destination.read_text(encoding='utf-8'))

    def test_invalid_config_creates_no_file_and_main_does_not_print_secret(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'api.env'
            output = io.StringIO()
            with mock.patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': 'private-token'}, clear=True), \
                    mock.patch('sys.argv', ['runtime_config.py', str(destination)]), \
                    contextlib.redirect_stderr(output):
                self.assertEqual(config.main(), 1)
            self.assertFalse(destination.exists())
            self.assertNotIn('private-token', output.getvalue())

    def test_compose_round_trip_preserves_password_punctuation(self):
        if shutil.which('docker') is None:
            self.skipTest('Docker Compose CLI is not installed')
        passwords = ['12345678', '$HOME ${PASSWORD} $$"quoted"',
                     'heslo # česky $(echo nope) `echo nope`']
        for password in passwords:
            with self.subTest(password=password), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                values = config.runtime_values({
                    'LEADS_ENABLED': 'true', 'TELEGRAM_BOT_TOKEN': TOKEN,
                    'TELEGRAM_ADMIN_PASSWORD': password,
                    'LEADS_ALLOWED_ORIGINS': 'http://129.101.120.192'})
                config.write_config(directory / 'api.env', values)
                (directory / 'compose.yaml').write_text(
                    'services:\n  check:\n    image: busybox\n    env_file:\n      - ./api.env\n',
                    encoding='utf-8')
                environment = dict(os.environ, DOCKER_CONFIG=str(directory))
                result = subprocess.run(
                    ['docker', '--config', str(directory), 'compose', '-f',
                     str(directory / 'compose.yaml'), 'config', '--format', 'json'],
                    capture_output=True, text=True, encoding='utf-8', env=environment, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                actual = json.loads(result.stdout)['services']['check']['environment']
                # Normal config resolves env_file across Compose versions. Its JSON
                # output doubles literal dollars so the rendered model can be reused.
                expected = {key: value.replace('$', '$$') for key, value in values.items()}
                self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
