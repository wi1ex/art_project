import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import Settings
from backend.auth import hash_password, verify_password
from backend.storage import Store
from backend import telegram
from backend.tests.test_telegram_menu import FakeSender, buttons, message


class TelegramPasswordFlowTests(unittest.TestCase):
    BOOTSTRAP = 'Bootstrap-Password-2026'
    NEW_PASSWORD = 'New-Administrator-Password'

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / 'leads.sqlite3')
        self.store = Store(self.path)
        self.settings = Settings(admin_password=self.BOOTSTRAP)
        self.sender = FakeSender()
        self.bot = telegram.TelegramBot(self.settings, self.store, self.sender)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def send(self, text, chat_id=42, **kwargs):
        asyncio.run(self.bot.handle_update(message(chat_id, text, **kwargs)))
        return self.sender.messages[-1] if self.sender.messages else None

    def begin(self, *, command='/password', current=None):
        self.send(command)
        self.send(self.BOOTSTRAP if current is None else current)

    def assert_no_secret_echo(self, *secrets):
        outgoing = '\n'.join(item[1] for item in self.sender.messages)
        for secret in secrets:
            self.assertNotIn(secret, outgoing)
        encoded = self.store.password_hash()
        if encoded:
            self.assertNotIn(encoded, outgoing)

    def test_password_change_requires_private_authenticated_chat(self):
        for command in ('/password', telegram.PASSWORD_BUTTON):
            self.send(command, chat_id=-100, chat_type='supergroup')
        self.assertEqual(self.sender.messages, [])
        for command in ('/password', telegram.PASSWORD_BUTTON):
            result = self.send(command, chat_id=43)
            self.assertIn(telegram.LOGIN_BUTTON, buttons(result))
        self.send(self.BOOTSTRAP, chat_id=43)
        self.send(self.NEW_PASSWORD, chat_id=43)
        self.send(self.NEW_PASSWORD, chat_id=43)
        self.assertIsNone(self.store.password_hash())
        self.assertFalse(self.store.is_admin(43))
        self.assertEqual(self.bot.password_changes, {})
        self.assert_no_secret_echo(self.BOOTSTRAP, self.NEW_PASSWORD)

    def test_wrong_current_password_cannot_advance_change(self):
        self.store.add_admin(42)
        self.send(telegram.PASSWORD_BUTTON)
        self.send('Incorrect-Current-Password')
        self.send(self.NEW_PASSWORD)
        self.send(self.NEW_PASSWORD)
        self.assertIsNone(self.store.password_hash())
        self.send(self.BOOTSTRAP)
        self.send(self.NEW_PASSWORD)
        self.assertIsNone(self.store.password_hash())
        self.send(self.NEW_PASSWORD)
        self.assertTrue(verify_password(self.NEW_PASSWORD, self.store.password_hash()))
        self.assert_no_secret_echo(self.BOOTSTRAP, self.NEW_PASSWORD, 'Incorrect-Current-Password')

    def test_invalid_or_same_new_password_leaves_saved_password_unchanged(self):
        self.store.add_admin(42)
        self.begin()
        for candidate in ('short', 'x' * 129, ' leading-new-password', 'trailing-new-password ', self.BOOTSTRAP):
            with self.subTest(candidate_type=len(candidate)):
                self.send(candidate)
                self.assertIsNone(self.store.password_hash())
        self.send(self.NEW_PASSWORD)
        self.assertIsNone(self.store.password_hash())
        self.send(self.NEW_PASSWORD)
        self.assertTrue(verify_password(self.NEW_PASSWORD, self.store.password_hash()))
        self.assert_no_secret_echo(self.BOOTSTRAP, self.NEW_PASSWORD)

    def test_repeat_mismatch_requires_a_new_password_and_never_keeps_plaintext(self):
        self.store.add_admin(42)
        replacement = 'Replacement-Administrator-Password'
        self.begin()
        self.send(self.NEW_PASSWORD)
        self.assertNotIn(self.NEW_PASSWORD, repr(self.bot.password_changes))
        saved_state = [tuple(row) for row in self.store.db.execute('SELECT key,value FROM bot_state')]
        self.assertNotIn(self.NEW_PASSWORD, repr(saved_state))
        self.assertIsNone(self.store.password_hash())
        self.send('Mismatched-Confirmation-Password')
        self.assertIsNone(self.store.password_hash())
        self.send(replacement)
        self.assertIsNone(self.store.password_hash())
        self.assertNotIn(replacement, repr(self.bot.password_changes))
        self.send(replacement)
        self.assertTrue(verify_password(replacement, self.store.password_hash()))
        self.assertFalse(verify_password(self.NEW_PASSWORD, self.store.password_hash()))
        self.assert_no_secret_echo(self.BOOTSTRAP, self.NEW_PASSWORD, replacement,
                                   'Mismatched-Confirmation-Password')

    def test_successful_global_change_revokes_other_admins_and_persists_across_restart(self):
        for chat_id in (42, 43, 44):
            self.store.add_admin(chat_id)
        self.store.save_offset(123)
        self.store.accept('original', '+420774411158', admin_chats=self.store.admin_chats())
        self.store.finish_delivery('original', '43', 'sent')
        self.assertIsNotNone(self.store.claim_delivery('original', '44'))
        snapshot = self.store.history_snapshot()
        self.send('/history', chat_id=43)
        self.send('/clear', chat_id=43)
        self.begin(command=telegram.PASSWORD_BUTTON)
        self.send(self.NEW_PASSWORD)
        self.assertIsNone(self.store.password_hash())
        self.send(self.NEW_PASSWORD)
        encoded = self.store.password_hash()
        self.assertTrue(encoded.startswith('pbkdf2_sha256$'))
        self.assertTrue(verify_password(self.NEW_PASSWORD, encoded))
        self.assertFalse(verify_password(self.BOOTSTRAP, encoded))
        self.assertEqual(self.store.admin_chats(), ['42'])
        self.assertEqual(self.store.history_count(through_id=snapshot), 1)
        self.assertEqual(self.store.update_offset(), 123)
        self.assertEqual({row['chat_id']: row['state'] for row in self.store.delivery_rows('original')},
                         {'42': 'pending', '43': 'sent', '44': 'cancelled'})
        self.assertEqual(self.store.delivered_chats('original'), ['43'])
        self.assertEqual(self.bot.pending_clears, {})
        self.assertEqual(self.bot.views, {})
        self.assertEqual(self.bot.password_changes, {})
        self.store.close()
        self.store = Store(self.path)
        self.bot = telegram.TelegramBot(self.settings, self.store, self.sender)
        self.assertEqual(self.store.password_hash(), encoded)
        self.assertTrue(self.store.is_admin(42))
        self.send('/start', chat_id=44)
        self.send(self.BOOTSTRAP, chat_id=44)
        self.assertFalse(self.store.is_admin(44))
        self.send(self.NEW_PASSWORD, chat_id=44)
        self.assertTrue(self.store.is_admin(44))
        self.assertEqual(self.store.history_count(through_id=snapshot), 1)
        self.assert_no_secret_echo(self.BOOTSTRAP, self.NEW_PASSWORD)

    def test_cancel_menu_and_logout_abandon_pending_password(self):
        for action in ('/cancel', telegram.CANCEL_BUTTON, telegram.MENU_BUTTON, '/start',
                       telegram.LOGOUT_BUTTON, '/logout'):
            with self.subTest(action=action):
                self.store.add_admin(42)
                self.begin()
                self.send(self.NEW_PASSWORD)
                self.send(action)
                self.send(self.NEW_PASSWORD)
                self.assertIsNone(self.store.password_hash())
                self.assertNotIn('42', self.bot.password_changes)
        self.assert_no_secret_echo(self.BOOTSTRAP, self.NEW_PASSWORD)

    def test_timeout_does_not_commit_a_password_awaiting_confirmation(self):
        self.store.add_admin(42)
        with patch('backend.telegram.time.monotonic', return_value=1000):
            self.begin()
            self.send(self.NEW_PASSWORD)
        with patch('backend.telegram.time.monotonic', return_value=1000 + telegram.PASSWORD_CHANGE_SECONDS):
            self.send(self.NEW_PASSWORD)
        self.assertIsNone(self.store.password_hash())
        self.assertNotIn('42', self.bot.password_changes)
        self.assert_no_secret_echo(self.BOOTSTRAP, self.NEW_PASSWORD)

    def test_external_password_change_wins_over_stale_confirmation(self):
        self.store.add_admin(42)
        external_password = 'Operator-Reset-Administrator-Password'
        external_hash = hash_password(external_password)
        self.begin()
        self.send(self.NEW_PASSWORD)
        self.assertTrue(self.store.set_password_hash(external_hash))
        self.send(self.NEW_PASSWORD)
        self.assertEqual(self.store.password_hash(), external_hash)
        self.assertNotIn('42', self.bot.password_changes)
        self.send('/start', chat_id=43)
        self.send(self.NEW_PASSWORD, chat_id=43)
        self.assertFalse(self.store.is_admin(43))
        self.send(external_password, chat_id=43)
        self.assertTrue(self.store.is_admin(43))
        self.assert_no_secret_echo(self.BOOTSTRAP, self.NEW_PASSWORD, external_password)

    def test_saved_password_is_required_for_later_change_instead_of_bootstrap(self):
        self.store.add_admin(42)
        saved_password = 'Previously-Saved-Administrator-Password'
        saved_hash = hash_password(saved_password)
        self.store.set_password_hash(saved_hash)
        self.send('/password')
        self.send(self.BOOTSTRAP)
        self.assertEqual(self.store.password_hash(), saved_hash)
        self.send(saved_password)
        self.send(self.NEW_PASSWORD)
        self.send(self.NEW_PASSWORD)
        self.assertTrue(verify_password(self.NEW_PASSWORD, self.store.password_hash()))
        self.assert_no_secret_echo(self.BOOTSTRAP, self.NEW_PASSWORD, saved_password)

    def test_failed_password_prompt_does_not_arm_change(self):
        self.store.add_admin(42)
        self.sender.fail_next = True
        self.send('/password')
        self.send(self.BOOTSTRAP)
        self.send(self.NEW_PASSWORD)
        self.send(self.NEW_PASSWORD)
        self.assertIsNone(self.store.password_hash())
        self.assertNotIn('42', self.bot.password_changes)
        self.assert_no_secret_echo(self.BOOTSTRAP, self.NEW_PASSWORD)

    def test_operator_reset_during_login_verification_rejects_stale_password(self):
        reset_password = 'Operator-Reset-During-Login'
        reset_hash = hash_password(reset_password)
        self.send('/start', chat_id=43)

        async def verification_finishes_after_reset(candidate, encoded):
            self.assertEqual(candidate, self.BOOTSTRAP)
            self.assertIsNone(encoded)
            self.store.set_password_hash(reset_hash, keep_admin_chat=None)
            return True

        with patch.object(self.bot, '_password_matches', side_effect=verification_finishes_after_reset):
            self.send(self.BOOTSTRAP, chat_id=43)
        self.assertFalse(self.store.is_admin(43))
        self.assertEqual(self.store.password_hash(), reset_hash)
        self.send('/start', chat_id=43)
        self.send(reset_password, chat_id=43)
        self.assertTrue(self.store.is_admin(43))
        self.assert_no_secret_echo(self.BOOTSTRAP, reset_password)


if __name__ == '__main__':
    unittest.main()
