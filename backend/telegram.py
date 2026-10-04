"""Telegram delivery and the small private-chat administration bot.

Telegram responses are deliberately never logged: API URLs contain the bot
token and lead text contains personal data.
"""
from datetime import datetime
from html import escape
import re
from zoneinfo import ZoneInfo

import httpx


PRIVATE_ADMIN_PASSWORD = '12345678'
WEEK_BUTTON = 'Посмотреть все заявки за неделю'


class TelegramSender:
    def __init__(self, settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    @staticmethod
    def _date(timestamp):
        return datetime.fromtimestamp(timestamp, ZoneInfo('Europe/Prague')).strftime(
            '%d.%m.%Y %H:%M:%S %Z'
        )

    def lead_text(self, row):
        return (
            'Новая заявка ART PROJECT\n'
            f"Дата: {self._date(row['created_at'])} (Europe/Prague)\n"
            f"Телефон: {row['phone']}"
        )

    async def _post(self, chat_id, text, reply_markup=None, parse_mode=None):
        payload = {'chat_id': str(chat_id), 'text': text}
        if reply_markup is not None:
            payload['reply_markup'] = reply_markup
        if parse_mode is not None:
            payload['parse_mode'] = parse_mode
            payload['link_preview_options'] = {'is_disabled': True}
        try:
            response = await self.client.post(
                f'https://api.telegram.org/bot{self.settings.telegram_token}/sendMessage',
                json=payload,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            return 'pending', self.settings.retry_seconds, 'connection_unavailable'
        except httpx.HTTPError:
            return 'unknown', self.settings.retry_seconds, 'delivery_unknown'
        if response.status_code >= 500:
            return 'unknown', self.settings.retry_seconds, 'telegram_server_error'
        try:
            data = response.json()
        except ValueError:
            return 'unknown', self.settings.retry_seconds, 'invalid_telegram_response'
        if not isinstance(data, dict):
            return 'unknown', self.settings.retry_seconds, 'invalid_telegram_response'
        if response.status_code == 200 and data.get('ok') is True:
            if isinstance(data.get('result'), dict) and type(data['result'].get('message_id')) is int:
                return 'sent', 0, ''
            return 'unknown', self.settings.retry_seconds, 'invalid_telegram_response'
        if data.get('ok') is False and data.get('error_code') == 429:
            parameters = data.get('parameters')
            retry = parameters.get('retry_after', self.settings.retry_seconds) if isinstance(parameters, dict) else self.settings.retry_seconds
            if type(retry) is not int:
                retry = self.settings.retry_seconds
            return 'pending', max(1, min(retry, 86400)), 'telegram_rate_limited'
        if data.get('ok') is False and type(data.get('error_code')) is int and 400 <= data['error_code'] < 500:
            return 'blocked', 0, f"telegram_{data['error_code']}"
        return 'unknown', self.settings.retry_seconds, 'delivery_unknown'

    async def send(self, row, recipients=None):
        """Send a lead to authenticated admins.

        This compatibility helper sends to every supplied private chat. The
        dispatcher uses ``send_one`` with durable per-admin delivery rows.
        """
        if recipients is None:
            recipients = []
        recipients = [str(value) for value in recipients if str(value)]
        # Every destination must have authenticated through a private /start
        # flow. A configured chat ID is ignored so it cannot bypass the gate.
        retry_interval = max(300, self.settings.retry_seconds)
        if not recipients:
            return 'pending', retry_interval, 'no_authenticated_admin'
        outcomes = []
        for chat_id in recipients:
            outcomes.append(await self._post(chat_id, self.lead_text(row)))
        if any(item[0] == 'sent' for item in outcomes):
            return 'sent', 0, ''
        delay = max(retry_interval, *(item[1] for item in outcomes))
        code = next((item[2] for item in outcomes if item[2]), 'delivery_failed')
        return 'pending', delay, code

    async def send_one(self, row, chat_id):
        """Deliver one lead to one authenticated chat.

        Per-admin delivery rows use a common five-minute retry floor. This
        keeps a rate limit or transient network failure from blocking already
        delivered administrators and prevents duplicate messages on retry.
        """
        state, delay, code = await self._post(chat_id, self.lead_text(row))
        if state == 'sent':
            return state, 0, code
        return 'pending', max(300, delay, self.settings.retry_seconds), code

    async def send_chat(self, chat_id, text, reply_markup=None, parse_mode=None):
        state, _, _ = await self._post(chat_id, text, reply_markup, parse_mode)
        return state == 'sent'

    async def get_updates(self, offset: int, timeout: int = 20):
        try:
            response = await self.client.get(
                f'https://api.telegram.org/bot{self.settings.telegram_token}/getUpdates',
                params={'offset': offset, 'timeout': timeout, 'allowed_updates': '["message"]'},
                timeout=timeout + 5,
            )
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        if response.status_code != 200 or not isinstance(data, dict) or data.get('ok') is not True:
            return None
        updates = data.get('result')
        return updates if isinstance(updates, list) else None


class TelegramBot:
    """Poll private Telegram messages and authenticate administrator chats."""

    def __init__(self, settings, store, sender):
        self.settings = settings
        self.store = store
        self.sender = sender
        self.offset = store.update_offset()
        self.awaiting_password: set[str] = set()

    @staticmethod
    def keyboard():
        return {
            'keyboard': [[{'text': WEEK_BUTTON}]],
            'resize_keyboard': True,
            'is_persistent': True,
        }

    @staticmethod
    def _command(text):
        if not isinstance(text, str):
            return ''
        first = text.strip().split(maxsplit=1)[0].lower() if text.strip() else ''
        if first.startswith('/'):
            return first.split('@', 1)[0]
        return first

    def _week_text(self):
        rows = self.store.week_leads()
        if not rows:
            return 'Заявок за последние 7 дней нет.'
        lines = [f'Заявки за последние 7 дней: {len(rows)}']
        for row in rows:
            lines.append(f"{TelegramSender._date(row['created_at'])} — {row['phone']}")
        text = '\n'.join(lines)
        return text

    def _week_messages(self):
        return self._chunk_blocks(self._week_text().splitlines())

    @staticmethod
    def _chunk_blocks(blocks, separator='\n'):
        """Keep whole lines/HTML entries and stay within Telegram's text limit.

        Counting raw HTML and UTF-16 units is deliberately conservative: it
        also covers characters outside the BMP without splitting an entity.
        Entries are bounded by stored Telegram profile/phone field limits.
        """
        messages = []
        current = ''
        for block in blocks:
            candidate = f'{current}{separator}{block}' if current else block
            if current and len(candidate.encode('utf-16-le')) // 2 > 4096:
                messages.append(current)
                current = block
            else:
                current = candidate
        if current:
            messages.append(current)
        return messages

    @staticmethod
    def _profile(user):
        user = user if isinstance(user, dict) else {}
        profile = {
            key: user.get(key, '')[:128] if isinstance(user.get(key, ''), str) else ''
            for key in ('first_name', 'last_name', 'username')
        }
        # Telegram usernames are restricted ASCII. Do not interpolate arbitrary
        # message metadata into profile links or an HTML attribute.
        if not re.fullmatch(r'[A-Za-z0-9_]{1,32}', profile['username']):
            profile['username'] = ''
        return profile

    def _admin_messages(self):
        admins = self.store.admins()
        blocks = [f'Зарегистрированные администраторы: {len(admins)}']
        for index, admin in enumerate(admins, 1):
            profile = self._profile(admin)
            name = ' '.join(value for value in (profile['first_name'], profile['last_name']) if value)
            username = profile['username']
            user_id = str(admin['user_id'])
            if username:
                url = f'https://t.me/{username}'
            elif user_id.isdigit() and int(user_id) > 0:
                url = f'tg://user?id={user_id}'
            else:
                url = ''
            link = f'<a href="{url}">Открыть профиль</a>' if url else 'Профиль недоступен'
            blocks.append(
                f'{index}. Имя: {escape(name or "Имя не указано")}\n'
                f'Ник: {"@" + username if username else "не указан"}\n'
                f'{link}\n'
                f'Регистрация: {TelegramSender._date(admin["added_at"])} (Europe/Prague)'
            )
        return self._chunk_blocks(blocks, separator='\n\n')

    async def handle_update(self, update):
        if not isinstance(update, dict):
            return
        message = update.get('message')
        if not isinstance(message, dict):
            return
        chat = message.get('chat')
        if not isinstance(chat, dict) or chat.get('type') != 'private':
            return
        chat_id = chat.get('id')
        if type(chat_id) not in (int, str):
            return
        chat_id = str(chat_id)
        user = message.get('from')
        user_id = user.get('id') if isinstance(user, dict) else chat_id
        profile = self._profile(user if isinstance(user, dict) else chat)
        text = message.get('text')
        command = self._command(text)
        is_admin = self.store.is_admin(chat_id)
        expected_password = getattr(self.settings, 'admin_password', PRIVATE_ADMIN_PASSWORD) or PRIVATE_ADMIN_PASSWORD
        if command == '/start':
            if is_admin:
                self.store.touch_admin(chat_id, profile=profile)
                await self.sender.send_chat(chat_id, 'Вы уже авторизованы как администратор. Команды: /week, /admins, /logout.', self.keyboard())
            else:
                self.awaiting_password.add(chat_id)
                await self.sender.send_chat(chat_id, 'Введите пароль администратора одним сообщением.')
            return
        if (not is_admin and chat_id in self.awaiting_password and isinstance(text, str)
                and text.strip() == expected_password):
            self.awaiting_password.discard(chat_id)
            self.store.add_admin(chat_id, user_id, **profile)
            await self.sender.send_chat(chat_id, 'Пароль принят. Вы авторизованы как администратор. Команды: /week, /admins, /logout.', self.keyboard())
            return
        if not is_admin:
            await self.sender.send_chat(chat_id, 'Сначала выполните /start и введите пароль администратора.')
            return
        self.store.touch_admin(chat_id, profile=profile)
        if command == '/logout':
            self.awaiting_password.discard(chat_id)
            self.store.remove_admin(chat_id)
            await self.sender.send_chat(
                chat_id, 'Вы вышли из администраторов. Для входа выполните /start и введите пароль.',
                {'remove_keyboard': True},
            )
        elif command == '/admins':
            messages = self._admin_messages()
            for index, result in enumerate(messages):
                await self.sender.send_chat(
                    chat_id, result, self.keyboard() if index == len(messages) - 1 else None,
                    parse_mode='HTML',
                )
        elif (command in ('/week', 'week')) or (isinstance(text, str) and text.strip() == WEEK_BUTTON):
            messages = self._week_messages()
            for index, result in enumerate(messages):
                await self.sender.send_chat(chat_id, result, self.keyboard() if index == len(messages) - 1 else None)

    async def poll_once(self, timeout: int = 20):
        updates = await self.sender.get_updates(self.offset, timeout)
        if updates is None:
            return False
        for update in updates:
            if isinstance(update, dict) and type(update.get('update_id')) is int:
                await self.handle_update(update)
                self.offset = max(self.offset, update['update_id'] + 1)
        self.store.save_offset(self.offset)
        return True

    async def run(self):
        import asyncio
        while True:
            try:
                ok = await self.poll_once()
                if not ok:
                    await asyncio.sleep(5)
            except Exception:
                await asyncio.sleep(5)
