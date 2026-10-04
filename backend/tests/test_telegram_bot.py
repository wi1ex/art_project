from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from backend.app import Settings
from backend.storage import Store
from backend.telegram import TelegramBot, TelegramSender, WEEK_BUTTON


class FakeSender:
    def __init__(self):
        self.messages: list[tuple[str, str, dict | None, str | None]] = []

    async def send_chat(self, chat_id, text, reply_markup=None, parse_mode=None):
        self.messages.append((str(chat_id), text, reply_markup, parse_mode))
        return True


def update(chat_id, text, *, chat_type='private', user_id=None, update_id=1,
           first_name='', last_name='', username=''):
    return {
        'update_id': update_id,
        'message': {
            'chat': {'id': chat_id, 'type': chat_type},
            'from': {'id': user_id if user_id is not None else chat_id,
                     'first_name': first_name, 'last_name': last_name, 'username': username},
            'text': text,
        },
    }


class TelegramBotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.directory.name) / 'leads.sqlite3'))
        self.sender = FakeSender()
        self.bot = TelegramBot(Settings(admin_password='12345678'), self.store, self.sender)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_private_start_requires_password_and_unlocks_week_button(self):
        asyncio.run(self.bot.handle_update(update(42, '/start')))
        self.assertFalse(self.store.is_admin(42))
        self.assertIn('пароль', self.sender.messages[-1][1].lower())

        asyncio.run(self.bot.handle_update(update(42, 'wrong')))
        self.assertFalse(self.store.is_admin(42))
        asyncio.run(self.bot.handle_update(update(42, '12345678')))
        self.assertTrue(self.store.is_admin(42))
        self.assertEqual(self.sender.messages[-1][2]['keyboard'][0][0]['text'], WEEK_BUTTON)

    def test_group_messages_are_ignored_and_week_is_admin_only(self):
        asyncio.run(self.bot.handle_update(update(-100, '/start', chat_type='supergroup')))
        self.assertEqual(self.sender.messages, [])
        asyncio.run(self.bot.handle_update(update(42, '/week')))
        self.assertIn('Сначала', self.sender.messages[-1][1])

        self.store.add_admin(42, 42)
        now = time.time()
        self.store.accept('new', '+420774411158', now=now - 2 * 86400)
        self.store.accept('old', '+420774411159', now=now - 8 * 86400)
        asyncio.run(self.bot.handle_update(update(42, 'week')))
        text = self.sender.messages[-1][1]
        self.assertIn('+420774411158', text)
        self.assertNotIn('+420774411159', text)
        self.assertNotIn('chat_id', text)
        self.assertNotIn('delivered_to', text)
        self.assertNotIn('sent', text.lower())
        self.assertNotIn('pending', text.lower())

    def test_update_offset_is_durable(self):
        self.bot.offset = 17
        self.store.save_offset(self.bot.offset)
        other = TelegramBot(Settings(), self.store, self.sender)
        self.assertEqual(other.offset, 17)

    def test_admins_requires_auth_and_ignores_groups(self):
        self.store.add_admin(42, 42, first_name='Private name')
        asyncio.run(self.bot.handle_update(update(43, '/admins')))
        self.assertIn('Сначала', self.sender.messages[-1][1])
        self.assertNotIn('Private name', self.sender.messages[-1][1])
        count = len(self.sender.messages)
        for command in ('/admins', '/logout'):
            asyncio.run(self.bot.handle_update(update(-100, command, chat_type='supergroup')))
        self.assertEqual(len(self.sender.messages), count)
        self.assertTrue(self.store.is_admin(42))

    def test_admins_lists_escaped_names_username_profile_and_registration_date(self):
        self.store.add_admin(42, 42, now=0, first_name='Иван <Admin>', last_name='& Co', username='owner42')
        self.store.add_admin(43, 43, now=86400, first_name='Без ника')
        asyncio.run(self.bot.handle_update(update(42, '/admins', first_name='Иван <Admin>',
                                                 last_name='& Co', username='owner42')))
        text, mode = self.sender.messages[-1][1], self.sender.messages[-1][3]
        self.assertEqual(mode, 'HTML')
        self.assertIn('Иван &lt;Admin&gt; &amp; Co', text)
        self.assertIn('@owner42', text)
        self.assertIn('href="https://t.me/owner42"', text)
        self.assertIn('href="tg://user?id=43"', text)
        self.assertIn('01.01.1970 01:00:00 CET (Europe/Prague)', text)
        self.assertIn('Ник: не указан', text)
        self.assertNotIn('<Admin>', text)

    def test_authorization_records_profile_and_refresh_does_not_reset_registration(self):
        asyncio.run(self.bot.handle_update(update(42, '/start')))
        with patch('backend.storage.time.time', return_value=1000):
            asyncio.run(self.bot.handle_update(update(42, '12345678', first_name='First',
                                                     last_name='Name', username='old_name')))
        self.assertEqual(self.store.admins()[0]['added_at'], 1000)
        with patch('backend.storage.time.time', return_value=2000):
            asyncio.run(self.bot.handle_update(update(42, '/week', first_name='Changed', username='new_name')))
        admin = self.store.admins()[0]
        self.assertEqual(admin['added_at'], 1000)
        self.assertEqual(admin['first_name'], 'Changed')
        self.assertEqual(admin['last_name'], '')
        self.assertEqual(admin['username'], 'new_name')

    def test_admin_list_chunks_complete_entries_with_emoji_and_escaped_html(self):
        for chat_id in range(1, 101):
            self.store.add_admin(chat_id, chat_id, first_name='😀<&' * 40,
                                 last_name='"' * 120, username=f'user_{chat_id}')
        asyncio.run(self.bot.handle_update(update(1, '/admins', first_name='Requester')))
        self.assertGreater(len(self.sender.messages), 1)
        text = '\n'.join(message[1] for message in self.sender.messages)
        for message in self.sender.messages:
            self.assertLessEqual(len(message[1].encode('utf-16-le')) // 2, 4096)
            self.assertEqual(message[1].count('<a '), message[1].count('</a>'))
        self.assertEqual(text.count('Регистрация:'), 100)
        self.assertIn('href="https://t.me/user_100"', text)

    def test_logout_removes_keyboard_and_requires_new_start_password(self):
        self.store.add_admin(42, 42, now=1000)
        self.store.accept('old', '+420774411158', admin_chats=self.store.admin_chats())
        asyncio.run(self.bot.handle_update(update(42, '/logout')))
        self.assertFalse(self.store.is_admin(42))
        self.assertEqual(self.sender.messages[-1][2], {'remove_keyboard': True})
        self.assertEqual(self.store.delivery_rows('old')[0]['state'], 'cancelled')
        self.assertEqual(self.store.get('old')['delivered_to'], '')
        for command in ('/week', '/admins', '12345678'):
            asyncio.run(self.bot.handle_update(update(42, command)))
            self.assertIn('Сначала', self.sender.messages[-1][1])
        asyncio.run(self.bot.handle_update(update(42, '/start')))
        with patch('backend.storage.time.time', return_value=3000):
            asyncio.run(self.bot.handle_update(update(42, '12345678', first_name='Again')))
        self.assertEqual(self.store.admins()[0]['added_at'], 3000)
        self.assertEqual(self.store.delivery_rows('old')[0]['state'], 'cancelled')
        self.store.accept('future', '+420774411159', admin_chats=self.store.admin_chats())
        self.assertEqual(self.store.delivery_rows('future')[0]['state'], 'pending')

    def test_logout_is_durable_after_restart(self):
        self.store.add_admin(42, 42)
        self.store.accept('old', '+420774411158', admin_chats=self.store.admin_chats())
        asyncio.run(self.bot.handle_update(update(42, '/logout')))
        self.store.close()
        self.store = Store(str(Path(self.directory.name) / 'leads.sqlite3'))
        self.assertFalse(self.store.is_admin(42))
        self.assertEqual(self.store.get('old')['state'], 'cancelled')
        self.assertEqual(self.store.delivery_rows('old')[0]['state'], 'cancelled')
        self.assertIsNone(self.store.claim())

    def test_legacy_admin_schema_is_migrated_without_resetting_registration(self):
        path = str(Path(self.directory.name) / 'legacy.sqlite3')
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE bot_admins(chat_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,'
                       'added_at REAL NOT NULL,last_seen REAL NOT NULL)')
            db.execute('INSERT INTO bot_admins VALUES(?,?,?,?)', ('42', '42', 1000, 2000))
        legacy = Store(path)
        try:
            self.assertTrue(legacy.is_admin(42))
            legacy.touch_admin(42, profile={'first_name': 'Migrated', 'last_name': '', 'username': 'old_user'})
            admin = legacy.admins()[0]
            self.assertEqual(admin['added_at'], 1000)
            self.assertEqual(admin['first_name'], 'Migrated')
            self.assertEqual(admin['username'], 'old_user')
        finally:
            legacy.close()

    def test_sender_transmits_html_links_without_preview(self):
        requests = []

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: requests.append(request) or httpx.Response(
                    200, json={'ok': True, 'result': {'message_id': 1}}
                )
            )) as client:
                sender = TelegramSender(Settings(telegram_token='test'), client)
                self.assertTrue(await sender.send_chat(42, '<a href="tg://user?id=42">Профиль</a>', parse_mode='HTML'))
        asyncio.run(run())
        payload = json.loads(requests[0].content)
        self.assertEqual(payload['parse_mode'], 'HTML')
        self.assertEqual(payload['link_preview_options'], {'is_disabled': True})


if __name__ == '__main__':
    unittest.main()
