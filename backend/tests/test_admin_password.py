"""Password storage and the authenticated-SSH recovery command."""
import contextlib
import getpass
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.auth import hash_password, validate_password, verify_password
from backend.cli import main, reset_admin_password
from backend.storage import Store


class PasswordHashTests(unittest.TestCase):
    def test_salted_hash_roundtrip_and_wrong_password(self):
        password = 'Надёжный пароль 2026'
        encoded = hash_password(password)
        self.assertNotIn(password, encoded)
        self.assertNotEqual(encoded, hash_password(password))
        self.assertTrue(verify_password(password, encoded))
        self.assertFalse(verify_password('Другой пароль 2026', encoded))

    def test_password_limits_and_whitespace_are_not_silently_changed(self):
        for candidate in ('short', 'x' * 129, ' xxxxxxxxxxxx', 'xxxxxxxxxxxx\n',
                          '/start long secret', 'Администраторы', 'Сменить пароль'):
            with self.subTest(candidate_length=len(candidate)):
                self.assertIsInstance(validate_password(candidate), str)
                with self.assertRaises(ValueError):
                    hash_password(candidate)
        self.assertIsNone(validate_password('x' * 12))
        self.assertIsNone(validate_password('я' * 128))

    def test_malformed_hash_and_unbounded_work_factor_fail_before_kdf(self):
        for encoded in ('', None, 'x' * 10000,
                        'pbkdf2_sha256$999999999999$' + '00' * 16 + '$' + '00' * 32,
                        'pbkdf2_sha256$600000$' + 'zz' * 16 + '$' + '00' * 32,
                        'pbkdf2_sha256$600000$' + '00' * 15 + '$' + '00' * 32):
            with self.subTest(encoded_type=type(encoded).__name__):
                with patch('backend.auth.hashlib.pbkdf2_hmac') as derive:
                    self.assertFalse(verify_password('a valid password', encoded))
                    derive.assert_not_called()


class PasswordPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / 'leads.sqlite3')
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_hash_persists_without_losing_admins_offset_or_history(self):
        self.assertIsNone(self.store.password_hash())
        self.store.add_admin(42)
        self.store.save_offset(123)
        self.store.accept('request', '+420123456789', admin_chats=['42'])
        encoded = hash_password('new admin password')
        self.assertTrue(self.store.set_password_hash(encoded))
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.password_hash(), encoded)
        self.assertTrue(self.store.is_admin(42))
        self.assertEqual(self.store.update_offset(), 123)
        self.assertEqual(self.store.history_count(through_id=self.store.history_snapshot()), 1)
        self.assertEqual(self.store.delivery_rows('request')[0]['state'], 'pending')

    def test_atomic_compare_and_swap_rejects_stale_change_and_bootstrap(self):
        self.assertTrue(self.store.set_password_hash('first', expected_hash=None))
        self.assertFalse(self.store.set_password_hash('bootstrap', expected_hash=None))
        self.assertFalse(self.store.set_password_hash('stale', expected_hash='old'))
        self.assertTrue(self.store.set_password_hash('second', expected_hash='first'))
        self.assertFalse(self.store.set_password_hash('racing-change', expected_hash='first'))
        self.assertEqual(self.store.password_hash(), 'second')

    def test_stale_password_change_does_not_revoke_other_admins(self):
        self.store.add_admin(42)
        self.store.add_admin(43)
        self.store.accept('request', '+420123456789', admin_chats=['43'])
        self.store.set_password_hash('current')
        self.assertFalse(self.store.set_password_hash(
            'stale-change', expected_hash='old', keep_admin_chat='42'
        ))
        self.assertFalse(self.store.set_password_hash(
            'stale-bootstrap', expected_hash=None, keep_admin_chat='42'
        ))
        self.assertTrue(self.store.is_admin(43))
        self.assertEqual(self.store.delivery_rows('request')[0]['state'], 'pending')
        self.assertEqual(self.store.password_hash(), 'current')

    def test_conditional_login_matches_bootstrap_only_before_hash_exists(self):
        self.assertTrue(self.store.add_admin_if_password_current(42, expected_hash=None))
        self.assertTrue(self.store.is_admin(42))
        self.assertFalse(self.store.add_admin_if_password_current(43, expected_hash='nonexistent'))
        self.assertFalse(self.store.is_admin(43))
        self.store.set_password_hash('first', keep_admin_chat=None)
        self.assertFalse(self.store.add_admin_if_password_current(42, expected_hash=None))
        self.assertFalse(self.store.is_admin(42))
        self.assertTrue(self.store.add_admin_if_password_current(43, expected_hash='first'))

    def test_conditional_login_cannot_undo_password_reset_and_admin_revocation(self):
        self.store.set_password_hash('old')
        self.assertTrue(self.store.add_admin_if_password_current(42, expected_hash='old'))
        self.store.accept('request', '+420123456789', admin_chats=['42'])
        # The operator resets while the bot verifies a captured old hash.
        self.store.set_password_hash('new', keep_admin_chat=None)
        self.assertFalse(self.store.add_admin_if_password_current(42, expected_hash='old'))
        self.assertFalse(self.store.is_admin(42))
        self.assertEqual(self.store.delivery_rows('request')[0]['state'], 'cancelled')
        self.assertTrue(self.store.add_admin_if_password_current(42, expected_hash='new'))
        self.assertEqual(self.store.due_deliveries('request'), [])

    def test_conditional_login_refresh_preserves_registration_and_stale_attempt_does_not_touch_profile(self):
        self.store.set_password_hash('current')
        with patch('backend.storage.time.time', return_value=1000):
            self.assertTrue(self.store.add_admin_if_password_current(
                42, 142, expected_hash='current', first_name='First', username='first'
            ))
        with patch('backend.storage.time.time', return_value=2000):
            self.assertTrue(self.store.add_admin_if_password_current(
                42, 242, expected_hash='current', first_name='Updated', username='updated'
            ))
        self.assertFalse(self.store.add_admin_if_password_current(
            42, 999, expected_hash='stale', first_name='Stale', username='stale'
        ))
        row = self.store.db.execute('SELECT * FROM bot_admins WHERE chat_id=\'42\'').fetchone()
        self.assertEqual(row['added_at'], 1000)
        self.assertEqual(row['last_seen'], 2000)
        self.assertEqual(row['user_id'], '242')
        self.assertEqual(row['first_name'], 'Updated')
        self.assertEqual(row['username'], 'updated')

    def test_password_change_and_revocations_roll_back_together_on_sql_error(self):
        for chat in (42, 43, 44):
            self.store.add_admin(chat)
        self.store.accept('request', '+420123456789', admin_chats=['43', '44'])
        self.store.set_password_hash('current')
        self.store.db.executescript("""
            CREATE TRIGGER fail_revocation BEFORE DELETE ON bot_admins
            WHEN OLD.chat_id='44' BEGIN SELECT RAISE(ABORT,'test failure'); END;
        """)
        with self.assertRaises(sqlite3.DatabaseError):
            self.store.set_password_hash('replacement', expected_hash='current', keep_admin_chat='42')
        self.assertEqual(self.store.password_hash(), 'current')
        self.assertEqual(set(self.store.admin_chats()), {'42', '43', '44'})
        self.assertEqual([row['state'] for row in self.store.delivery_rows('request')], ['pending', 'pending'])

    def test_rotation_keeps_initiator_and_successes_cancels_only_unconfirmed(self):
        for chat in (42, 43, 44, 45):
            self.store.add_admin(chat)
        self.store.save_offset(123)
        self.store.accept('request', '+420123456789', admin_chats=['43', '44', '45'])
        self.store.accept('kept-request', '+420123456780', admin_chats=['42'])
        self.store.finish_delivery('request', '43', state='sent')
        self.store.claim_delivery('request', '45')
        self.store.set_password_hash('current')
        self.assertTrue(self.store.set_password_hash('replacement', expected_hash='current', keep_admin_chat='42'))
        self.assertEqual(self.store.admin_chats(), ['42'])
        self.assertEqual([row['state'] for row in self.store.delivery_rows('request')], ['sent', 'cancelled', 'cancelled'])
        self.assertEqual(self.store.get('request')['state'], 'cancelled')
        self.assertEqual(self.store.delivery_rows('kept-request')[0]['state'], 'pending')
        # Telegram may acknowledge a send already in flight when access changed.
        self.store.finish_delivery('request', '45', state='sent')
        self.assertEqual(self.store.delivered_chats('request'), ['43', '45'])
        self.assertEqual(self.store.delivery_rows('request')[2]['state'], 'sent')
        self.store.add_admin(44)
        self.assertEqual(self.store.due_deliveries('request'), [])
        self.assertEqual(self.store.update_offset(), 123)
        self.assertEqual(self.store.history_count(through_id=self.store.history_snapshot()), 2)

    def test_cli_reset_is_seen_live_and_revokes_all_without_startup_recovery(self):
        self.store.add_admin(42)
        self.store.save_offset(123)
        self.store.accept('request', '+420123456789', admin_chats=['42'])
        self.store.claim()
        self.store.claim_delivery('request', '42')
        output = io.StringIO()
        with patch('backend.cli.getpass.getpass', side_effect=['new secure password'] * 2):
            with patch('sys.argv', ['operator', 'reset-admin-password']):
                with patch.dict('os.environ', {'DATABASE_PATH': self.path}):
                    with contextlib.redirect_stdout(output):
                        main()
        encoded = self.store.password_hash()
        self.assertTrue(verify_password('new secure password', encoded))
        self.assertNotIn('new secure password', output.getvalue())
        self.assertNotIn(encoded, output.getvalue())
        self.assertEqual(self.store.get('request')['state'], 'cancelled')
        self.assertEqual(self.store.delivery_rows('request')[0]['state'], 'cancelled')
        self.assertEqual(self.store.delivery_rows('request')[0]['next_attempt'], 0)
        self.assertEqual(self.store.update_offset(), 123)
        self.assertFalse(self.store.is_admin(42))
        self.assertEqual(self.store.history_count(through_id=self.store.history_snapshot()), 1)

    def test_cli_password_and_revocations_roll_back_together(self):
        self.store.add_admin(42)
        self.store.set_password_hash('current')
        self.store.db.executescript("""
            CREATE TRIGGER fail_revocation BEFORE DELETE ON bot_admins
            BEGIN SELECT RAISE(ABORT,'test failure'); END;
        """)
        with patch('backend.cli.getpass.getpass', side_effect=['new secure password'] * 2):
            with self.assertRaises(sqlite3.DatabaseError):
                reset_admin_password(self.store.db)
        self.assertEqual(self.store.password_hash(), 'current')
        self.assertTrue(self.store.is_admin(42))

    def test_cli_mismatch_or_invalid_password_preserves_existing_hash(self):
        self.store.set_password_hash('unchanged')
        for inputs in (['new secure password', 'different password'], ['short']):
            with self.subTest(input_count=len(inputs)):
                with patch('backend.cli.getpass.getpass', side_effect=inputs):
                    with self.assertRaises(ValueError):
                        reset_admin_password(self.store.db)
                self.assertEqual(self.store.password_hash(), 'unchanged')

    def test_cli_refuses_visible_getpass_fallback(self):
        with patch('backend.cli.getpass.getpass', side_effect=getpass.GetPassWarning):
            with self.assertRaisesRegex(ValueError, 'интерактивный терминал'):
                reset_admin_password(self.store.db)
        self.assertIsNone(self.store.password_hash())

    def test_cli_does_not_create_missing_database(self):
        missing = str(Path(self.directory.name) / 'missing.sqlite3')
        with patch('sys.argv', ['operator', 'reset-admin-password']):
            with patch.dict('os.environ', {'DATABASE_PATH': missing}):
                with self.assertRaises(sqlite3.OperationalError):
                    main()
        self.assertFalse(Path(missing).exists())


if __name__ == '__main__':
    unittest.main()
