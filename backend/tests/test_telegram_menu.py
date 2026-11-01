import asyncio
import json
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from backend.app import Dispatcher, Settings
from backend.storage import Store
from backend import telegram


def message(chat_id, text, *, chat_type='private', update_id=1):
    return {
        'update_id': update_id,
        'message': {
            'chat': {'id': chat_id, 'type': chat_type},
            'from': {'id': chat_id, 'first_name': 'Requester'},
            'text': text,
        },
    }


class FakeSender:
    def __init__(self):
        self.messages = []
        self.delivered = []
        self.fail_next = False

    async def send_chat(self, chat_id, text, reply_markup=None, parse_mode=None):
        result = (str(chat_id), text, reply_markup, parse_mode)
        self.messages.append(result)
        if self.fail_next:
            self.fail_next = False
            return False
        self.delivered.append(result)
        return True


def buttons(result):
    return {button['text'] for row in (result[2] or {}).get('keyboard', []) for button in row}


def phones(result):
    return re.findall(r'\+[0-9]{8,15}', result[1])


class TelegramMenuTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / 'leads.sqlite3')
        self.store = Store(self.path)
        self.settings = Settings(telegram_token='test-token', admin_password='test-password')
        self.sender = FakeSender()
        self.bot = telegram.TelegramBot(self.settings, self.store, self.sender)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def send(self, text, chat_id=42, **kwargs):
        asyncio.run(self.bot.handle_update(message(chat_id, text, **kwargs)))
        return self.sender.messages[-1]

    def accept(self, index, *, now=None, admin_chats=()):
        request_id, phone = f'lead-{index}', f'+4207{index:08d}'
        self.store.accept(request_id, phone, now=now, admin_chats=admin_chats)
        return phone

    def test_start_describes_commands_and_exposes_complete_authorized_keyboard(self):
        commands = ('/start', '/week', '/history', '/admins', '/clear', '/help', '/logout', '/password')
        entry = self.send('/start')
        self.assertFalse(self.store.is_admin(42))
        self.assertTrue({telegram.LOGIN_BUTTON, telegram.HELP_BUTTON} <= buttons(entry))
        for command in commands:
            self.assertIn(command, entry[1])
        self.store.add_admin(42)
        authorized = self.send('/start')
        expected_buttons = {
            telegram.WEEK_BUTTON, telegram.HISTORY_BUTTON, telegram.ADMINS_BUTTON,
            telegram.HELP_BUTTON, telegram.CLEAR_BUTTON, telegram.LOGOUT_BUTTON,
            telegram.MENU_BUTTON, telegram.PASSWORD_BUTTON,
        }
        self.assertTrue(expected_buttons <= buttons(authorized))
        for command in commands:
            self.assertIn(command, authorized[1])
        self.assertEqual(authorized[2]['is_persistent'], True)

    def test_week_history_admin_help_and_menu_aliases_route_from_buttons(self):
        self.store.add_admin(42)
        self.store.add_admin(43, first_name='Other administrator')
        now = time.time()
        recent = self.accept(1, now=now - 86400)
        old = self.accept(2, now=now - 8 * 86400)
        for alias in (telegram.WEEK_BUTTON, '/week', '/week@ArtProjectBot', 'week',
                      'Посмотреть все заявки за неделю'):
            with self.subTest(alias=alias):
                result = self.send(alias)
                self.assertIn(recent, phones(result))
                self.assertNotIn(old, phones(result))
        for alias in (telegram.HISTORY_BUTTON, '/history', '/all', '/ALL@ArtProjectBot'):
            with self.subTest(alias=alias):
                self.assertEqual(set(phones(self.send(alias))), {recent, old})
        for alias in (telegram.ADMINS_BUTTON, '/admins'):
            with self.subTest(alias=alias):
                result = self.send(alias)
                self.assertIn('Other administrator', result[1])
                self.assertEqual(result[3], 'HTML')
        for alias in (telegram.HELP_BUTTON, '/help', telegram.MENU_BUTTON, telegram.LOGIN_BUTTON):
            with self.subTest(alias=alias):
                result = self.send(alias)
                self.assertIn('/history', result[1])
                self.assertIn('/clear', result[1])
                self.assertIn(telegram.HISTORY_BUTTON, buttons(result))
        for alias in (telegram.LOGOUT_BUTTON, '/logout'):
            with self.subTest(alias=alias):
                self.store.add_admin(42)
                result = self.send(alias)
                self.assertFalse(self.store.is_admin(42))
                self.assertIn(telegram.LOGIN_BUTTON, buttons(result))

    def test_history_and_clear_require_private_authenticated_chat(self):
        private_phone = self.accept(1)
        self.store.add_admin(42)
        aliases = (telegram.HISTORY_BUTTON, '/history', '/all', telegram.CLEAR_BUTTON,
                   '/clear', telegram.CONFIRM_CLEAR_BUTTON, '/confirm_clear', '/next', '/prev')
        for alias in aliases:
            with self.subTest(alias=alias):
                result = self.send(alias, chat_id=43)
                self.assertNotIn(private_phone, result[1])
                self.assertIn(telegram.LOGIN_BUTTON, buttons(result))
                self.assertNotIn('43', self.bot.pending_clears)
                self.assertNotIn('43', self.bot.views)
        sent_before_groups = len(self.sender.messages)
        self.store.add_admin(-100)
        for alias in aliases:
            self.send(alias, chat_id=-100, chat_type='supergroup')
        self.assertEqual(len(self.sender.messages), sent_before_groups)
        self.assertEqual(self.store.history_count(through_id=self.store.history_snapshot()), 1)

    def test_pages_use_25_rows_stable_snapshot_and_separate_chat_cursors(self):
        self.store.add_admin(42)
        self.store.add_admin(43)
        now = time.time() - 86400
        expected = [self.accept(index, now=now + index) for index in range(55)]
        first = self.send(telegram.HISTORY_BUTTON)
        self.assertEqual(phones(first), list(reversed(expected[30:55])))
        self.assertIn(telegram.NEXT_BUTTON, buttons(first))
        self.assertNotIn(telegram.PREVIOUS_BUTTON, buttons(first))
        new_phone = self.accept(55, now=now + 100)
        second = self.send(telegram.NEXT_BUTTON)
        self.assertEqual(phones(second), list(reversed(expected[5:30])))
        other_chat = self.send('/history', chat_id=43)
        self.assertEqual(phones(other_chat)[0], new_phone)
        third = self.send('/next')
        self.assertEqual(phones(third), list(reversed(expected[:5])))
        self.assertIn(telegram.PREVIOUS_BUTTON, buttons(third))
        self.assertNotIn(telegram.NEXT_BUTTON, buttons(third))
        self.assertEqual(phones(self.send(telegram.PREVIOUS_BUTTON)), phones(second))
        self.assertEqual(phones(self.send('/prev')), phones(first))
        self.assertEqual(phones(self.send('/prev')), phones(first))
        self.assertEqual(self.bot.views['43'].offset, 0)

    def test_failed_page_send_keeps_last_delivered_cursor(self):
        self.store.add_admin(42)
        now = time.time() - 1000
        for index in range(30):
            self.accept(index, now=now + index)
        first = self.send('/history')
        delivered_before = len(self.sender.delivered)
        self.sender.fail_next = True
        attempted = self.send('/next')
        self.assertNotEqual(phones(attempted), phones(first))
        self.assertEqual(self.bot.views['42'].offset, 0)
        self.assertEqual(len(self.sender.delivered), delivered_before)
        repeated = self.send(telegram.NEXT_BUTTON)
        self.assertEqual(phones(repeated), phones(attempted))
        self.assertEqual(self.bot.views['42'].offset, 25)

    def test_clear_requires_separate_confirmation_and_preserves_new_arrivals_and_outbox(self):
        self.store.add_admin(42)
        self.store.add_admin(43)
        self.store.save_offset(123)
        old_phone = self.accept(1, admin_chats=self.store.admin_chats())
        prompt = self.send(telegram.CLEAR_BUTTON)
        self.assertEqual(self.store.history_count(through_id=self.store.history_snapshot()), 1)
        self.assertTrue({telegram.CONFIRM_CLEAR_BUTTON, telegram.CANCEL_BUTTON} <= buttons(prompt))
        new_phone = self.accept(2, admin_chats=self.store.admin_chats())
        self.send(telegram.CONFIRM_CLEAR_BUTTON)
        result = self.send(telegram.HISTORY_BUTTON)
        self.assertEqual(phones(result), [new_phone])
        self.assertNotIn(old_phone, result[1])
        self.assertEqual(set(self.store.admin_chats()), {'42', '43'})
        self.assertEqual(self.store.update_offset(), 123)
        self.assertEqual(self.store.get('lead-1')['state'], 'pending')
        self.assertEqual({row['chat_id'] for row in self.store.delivery_rows('lead-1')}, {'42', '43'})
        self.assertEqual(self.store.accept('lead-1', old_phone), 'existing')
        self.store.close()
        self.store = Store(self.path)
        self.bot = telegram.TelegramBot(self.settings, self.store, self.sender)
        self.assertEqual(phones(self.send('/history')), [new_phone])
        self.send(telegram.CONFIRM_CLEAR_BUTTON)
        self.assertEqual(self.store.history_count(through_id=self.store.history_snapshot()), 1)

    def test_undelivered_clear_prompt_never_arms_confirmation(self):
        self.store.add_admin(42)
        self.accept(1)
        self.sender.fail_next = True
        self.send('/clear')
        self.assertNotIn('42', self.bot.pending_clears)
        self.send(telegram.CONFIRM_CLEAR_BUTTON)
        self.assertEqual(self.store.history_count(through_id=self.store.history_snapshot()), 1)
        # An argument appended to /clear is still only a request for a prompt.
        self.send('/clear yes')
        self.assertEqual(self.store.history_count(through_id=self.store.history_snapshot()), 1)

    def test_cancel_help_menu_and_logout_abandon_confirmation(self):
        self.store.add_admin(42)
        self.accept(1)
        for action in (telegram.CANCEL_BUTTON, '/cancel', telegram.HELP_BUTTON, '/help',
                       telegram.MENU_BUTTON, '/start', telegram.LOGOUT_BUTTON, '/logout'):
            with self.subTest(action=action):
                self.store.add_admin(42)
                self.send('/clear')
                self.send(action)
                self.store.add_admin(42)
                self.send(telegram.CONFIRM_CLEAR_BUTTON)
                self.assertNotIn('42', self.bot.pending_clears)
                self.assertEqual(self.store.history_count(through_id=self.store.history_snapshot()), 1)

    def test_confirmation_expires_and_other_chat_cannot_confirm_it(self):
        self.store.add_admin(42)
        self.store.add_admin(43)
        self.accept(1)
        with patch('backend.telegram.time.monotonic', return_value=1000):
            self.send('/clear')
        self.send(telegram.CONFIRM_CLEAR_BUTTON, chat_id=43)
        self.assertEqual(self.store.history_count(through_id=self.store.history_snapshot()), 1)
        with patch('backend.telegram.time.monotonic', return_value=1000 + telegram.CLEAR_CONFIRM_SECONDS):
            self.send(telegram.CONFIRM_CLEAR_BUTTON)
        self.assertNotIn('42', self.bot.pending_clears)
        self.assertEqual(self.store.history_count(through_id=self.store.history_snapshot()), 1)

    def test_restart_and_replayed_confirmation_cannot_clear_later_history(self):
        self.store.add_admin(42)
        self.accept(1)
        self.send('/clear')
        self.bot = telegram.TelegramBot(self.settings, self.store, self.sender)
        self.send(telegram.CONFIRM_CLEAR_BUTTON)
        self.assertEqual(self.store.history_count(through_id=self.store.history_snapshot()), 1)
        self.send('/clear')
        confirmation = message(42, telegram.CONFIRM_CLEAR_BUTTON, update_id=50)
        asyncio.run(self.bot.handle_update(confirmation))
        self.assertEqual(self.store.history_snapshot(), 0)
        new_phone = self.accept(2)
        asyncio.run(self.bot.handle_update(confirmation))
        self.assertEqual(phones(self.send('/history')), [new_phone])

    def test_clear_during_awaited_delivery_keeps_pending_and_actual_success(self):
        self.store.add_admin(42)
        self.store.add_admin(43)
        self.accept(1, now=time.time() - 100, admin_chats=self.store.admin_chats())
        attempts = []

        async def scenario():
            entered = asyncio.Event()
            release = asyncio.Event()

            async def response(request):
                payload = json.loads(request.content)
                chat_id = payload['chat_id']
                attempts.append(chat_id)
                if chat_id == '42':
                    entered.set()
                    await release.wait()
                elif attempts.count('43') == 1:
                    raise httpx.ConnectError('temporary connection failure', request=request)
                return httpx.Response(200, json={'ok': True, 'result': {'message_id': len(attempts)}})

            async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
                dispatcher = Dispatcher(self.store, telegram.TelegramSender(self.settings, client), self.settings)
                await self.bot.handle_update(message(42, '/clear'))
                task = asyncio.create_task(dispatcher.dispatch_once())
                try:
                    await asyncio.wait_for(entered.wait(), timeout=2)
                    await self.bot.handle_update(message(42, telegram.CONFIRM_CLEAR_BUTTON))
                    self.assertEqual(self.store.history_snapshot(), 0)
                    self.assertEqual(self.store.get('lead-1')['state'], 'sending')
                    new_phone = self.accept(2)
                finally:
                    release.set()
                    await asyncio.wait_for(task, timeout=2)
                self.assertEqual(self.store.get('lead-1')['state'], 'pending')
                self.assertEqual({row['chat_id']: row['state'] for row in self.store.delivery_rows('lead-1')},
                                 {'42': 'sent', '43': 'pending'})
                self.assertEqual(self.store.delivered_chats('lead-1'), ['42'])
                self.assertEqual([row['phone'] for row in self.store.history_leads(
                    through_id=self.store.history_snapshot()
                )], [new_phone])
                with self.store.db:
                    self.store.db.execute("UPDATE leads SET next_attempt=0 WHERE request_id='lead-1'")
                    self.store.db.execute("UPDATE lead_deliveries SET next_attempt=0 WHERE request_id='lead-1' AND state='pending'")
                self.assertTrue(await dispatcher.dispatch_once())
                self.assertEqual(self.store.get('lead-1')['state'], 'sent')
                self.assertEqual(self.store.delivered_chats('lead-1'), ['42', '43'])
                self.assertEqual(self.store.history_count(through_id=self.store.history_snapshot()), 1)

        asyncio.run(scenario())
        self.assertEqual(attempts, ['42', '43', '43'])


if __name__ == '__main__':
    unittest.main()
