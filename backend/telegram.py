"""Telegram delivery and the small private-chat administration bot.

Telegram responses are deliberately never logged: API URLs contain the bot
token and lead text contains personal data.
"""
import asyncio
from datetime import datetime
from dataclasses import dataclass, replace
from html import escape
import hmac
import re
import time
from zoneinfo import ZoneInfo

import httpx

from backend.auth import hash_password, validate_password, verify_password
from backend.bot_ui import (
    ADMINS_BUTTON, BUTTON_COMMANDS, CANCEL_BUTTON, CLEAR_BUTTON, CONFIRM_CLEAR_BUTTON,
    HELP_BUTTON, HISTORY_BUTTON, LOGIN_BUTTON, LOGOUT_BUTTON, MENU_BUTTON,
    NEXT_BUTTON, PASSWORD_BUTTON, PREVIOUS_BUTTON, WEEK_BUTTON,
)


PRIVATE_ADMIN_PASSWORD = '12345678'
PAGE_SIZE = 25
CLEAR_CONFIRM_SECONDS = 120
PASSWORD_CHANGE_SECONDS = 300


@dataclass(frozen=True)
class LeadView:
    through_id: int
    since: float | None = None
    offset: int = 0


@dataclass(frozen=True)
class PasswordChange:
    stage: str
    expires_at: float
    original_hash: str | None = None
    new_hash: str | None = None


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
        self.views: dict[str, LeadView] = {}
        self.pending_clears: dict[str, tuple[int, float]] = {}
        self.password_changes: dict[str, PasswordChange] = {}

    @staticmethod
    def keyboard(*, previous=False, next_page=False):
        rows = [
            [{'text': WEEK_BUTTON}, {'text': HISTORY_BUTTON}],
            [{'text': ADMINS_BUTTON}, {'text': HELP_BUTTON}],
            [{'text': CLEAR_BUTTON}, {'text': PASSWORD_BUTTON}],
            [{'text': MENU_BUTTON}, {'text': LOGOUT_BUTTON}],
        ]
        navigation = ([{'text': PREVIOUS_BUTTON}] if previous else []) + (
            [{'text': NEXT_BUTTON}] if next_page else [])
        if navigation:
            rows.insert(0, navigation)
        return {
            'keyboard': rows,
            'resize_keyboard': True,
            'is_persistent': True,
        }

    @staticmethod
    def entry_keyboard():
        return {
            'keyboard': [[{'text': LOGIN_BUTTON}, {'text': HELP_BUTTON}]],
            'resize_keyboard': True,
            'is_persistent': True,
        }

    @staticmethod
    def help_text():
        return (
            'Возможности бота ART PROJECT\n\n'
            '/start — «Войти» или «Меню». Вход по паролю администратора; '
            'после входа открывает это меню и обновляет кнопки. '
            'Новые заявки приходят автоматически всем авторизованным администраторам.\n\n'
            '/week — «Заявки за неделю». Общий список заявок за последние 7 дней '
            'с телефоном и временем поступления.\n\n'
            '/history (или /all) — «Вся история». Все сохранённые заявки, '
            'включая заявки старше недели. Сначала показываются новые, по 25 на странице. '
            'Листайте кнопками «Предыдущая страница» и «Следующая страница». '
            'История сохраняется до ручной очистки. Время указано по Праге.\n\n'
            '/admins — «Администраторы». Список авторизованных администраторов: '
            'имя, ник, ссылка на профиль и дата регистрации.\n\n'
            '/clear — «Очистить список». Очистка общей истории для всех администраторов '
            'после отдельного подтверждения. Подтверждение действует 2 минуты; '
            '«Отмена» возвращает меню. Заявки, пришедшие после запроса очистки, сохраняются. '
            'Уже отправленные сообщения остаются в чатах; ожидающие уведомления продолжают доставляться.\n\n'
            '/help — «Помощь». Повторно показывает описание всех действий.\n\n'
            '/password — «Сменить пароль». Меняет общий пароль для входа в бота. '
            'Введите текущий пароль, затем новый (12–128 символов) и повторите новый. '
            'На действие даётся 5 минут; «Отмена» прекращает смену. Ваш доступ сохранится, '
            'остальным администраторам потребуется снова войти с новым паролем.\n\n'
            '/logout — «Выйти». Завершает ваш доступ администратора и отключает '
            'дальнейшие уведомления в этом чате. Для возвращения снова нажмите «Войти» '
            'или отправьте /start и введите пароль.'
        )

    @staticmethod
    def _command(text):
        if not isinstance(text, str):
            return ''
        first = text.strip().split(maxsplit=1)[0].lower() if text.strip() else ''
        if first.startswith('/'):
            return first.split('@', 1)[0]
        return first

    async def _show_leads(self, chat_id, view):
        total = self.store.history_count(through_id=view.through_id, since=view.since)
        if not total:
            self.views.pop(chat_id, None)
            text = 'Заявок за последние 7 дней нет.' if view.since is not None else 'История заявок пуста.'
            await self.sender.send_chat(chat_id, text, self.keyboard())
            return
        last_offset = (total - 1) // PAGE_SIZE * PAGE_SIZE
        view = replace(view, offset=max(0, min(view.offset, last_offset)))
        rows = self.store.history_leads(
            through_id=view.through_id, since=view.since, offset=view.offset, limit=PAGE_SIZE,
        )
        title = 'Заявки за последние 7 дней' if view.since is not None else 'Вся история заявок'
        lines = [f'{title}: {total}', f'Страница {view.offset // PAGE_SIZE + 1} из {(total - 1) // PAGE_SIZE + 1}', '']
        lines.extend(f"{TelegramSender._date(row['created_at'])} — {row['phone']}" for row in rows)
        sent = await self.sender.send_chat(
            chat_id, '\n'.join(lines),
            self.keyboard(previous=view.offset > 0, next_page=view.offset + PAGE_SIZE < total),
        )
        # A failed page delivery must not advance the user's pagination cursor.
        if sent:
            self.views[chat_id] = view

    async def _request_clear(self, chat_id):
        self.pending_clears.pop(chat_id, None)
        through_id = self.store.history_snapshot()
        count = self.store.history_count(through_id=through_id)
        if not count:
            await self.sender.send_chat(chat_id, 'История заявок уже пуста.', self.keyboard())
            return
        sent = await self.sender.send_chat(
            chat_id,
            f'Очистить общий список заявок? Сейчас в нём: {count}.\n\n'
            'Будут удалены из истории все заявки, которые были в списке при этом запросе, '
            'для всех администраторов. Восстановить их через бота нельзя. '
            'Новые заявки, пришедшие после запроса, сохранятся.\n\n'
            'Сообщения в Telegram останутся в чатах. Ожидающие уведомления продолжат доставляться. '
            'Доступ администраторов сохранится.\n\n'
            'Нажмите «Да, очистить список» в течение 2 минут или «Отмена».',
            {'keyboard': [[{'text': CONFIRM_CLEAR_BUTTON}], [{'text': CANCEL_BUTTON}]],
             'resize_keyboard': True, 'is_persistent': True},
        )
        if sent:
            self.pending_clears[chat_id] = (through_id, time.monotonic() + CLEAR_CONFIRM_SECONDS)

    async def _confirm_clear(self, chat_id):
        pending = self.pending_clears.get(chat_id)
        if not pending:
            await self.sender.send_chat(chat_id, 'Нет активного запроса очистки. Нажмите «Очистить список», чтобы начать.', self.keyboard())
            return
        through_id, expires_at = pending
        if time.monotonic() >= expires_at:
            self.pending_clears.pop(chat_id, None)
            await self.sender.send_chat(chat_id, 'Время подтверждения истекло. При необходимости нажмите «Очистить список» ещё раз.', self.keyboard())
            return
        deleted = self.store.clear_history(through_id)
        self.pending_clears.clear()
        self.views.clear()
        await self.sender.send_chat(chat_id, f'Общий список очищен. Удалено заявок из истории: {deleted}. Новые заявки продолжат поступать.', self.keyboard())

    async def _password_matches(self, candidate, encoded):
        if not isinstance(candidate, str) or len(candidate) > (128 if encoded is not None else 256):
            return False
        if encoded is not None:
            # Password derivation must not stall lead delivery on the event loop.
            return await asyncio.to_thread(verify_password, candidate, encoded)
        expected = getattr(self.settings, 'admin_password', PRIVATE_ADMIN_PASSWORD) or PRIVATE_ADMIN_PASSWORD
        try:
            return hmac.compare_digest(candidate.strip().encode('utf-8'), expected.encode('utf-8'))
        except UnicodeError:
            return False

    @staticmethod
    def cancel_keyboard():
        return {'keyboard': [[{'text': CANCEL_BUTTON}]], 'resize_keyboard': True, 'is_persistent': True}

    async def _request_password_change(self, chat_id):
        self.password_changes.pop(chat_id, None)
        sent = await self.sender.send_chat(
            chat_id, 'Смена общего пароля администратора.\n\n'
            'После смены остальные администраторы выйдут из бота и должны будут войти заново. '
            'Ваш доступ сохранится.\n\n'
            'Введите текущий пароль одним сообщением. На смену даётся 5 минут; для выхода нажмите «Отмена».',
            self.cancel_keyboard(),
        )
        if sent:
            self.password_changes[chat_id] = PasswordChange('current', time.monotonic() + PASSWORD_CHANGE_SECONDS)

    async def _password_step(self, chat_id, text):
        state = self.password_changes[chat_id]
        if time.monotonic() >= state.expires_at:
            self.password_changes.pop(chat_id, None)
            await self.sender.send_chat(chat_id, 'Время смены пароля истекло. Начните заново кнопкой «Сменить пароль».', self.keyboard())
            return
        if not isinstance(text, str):
            await self.sender.send_chat(chat_id, 'Введите пароль текстовым сообщением или нажмите «Отмена».', self.cancel_keyboard())
            return
        if state.stage == 'current':
            original_hash = self.store.password_hash()
            if not await self._password_matches(text, original_hash):
                await self.sender.send_chat(chat_id, 'Текущий пароль не подошёл. Попробуйте снова или нажмите «Отмена».', self.cancel_keyboard())
                return
            self.password_changes[chat_id] = replace(state, stage='new', original_hash=original_hash)
            await self.sender.send_chat(chat_id, 'Введите новый пароль: от 12 до 128 символов, без пробелов в начале и конце.', self.cancel_keyboard())
            return
        if state.stage == 'new':
            error = validate_password(text)
            if error:
                await self.sender.send_chat(chat_id, error + ' Введите другой пароль или нажмите «Отмена».', self.cancel_keyboard())
                return
            if await self._password_matches(text, state.original_hash):
                await self.sender.send_chat(chat_id, 'Новый пароль должен отличаться от текущего. Введите другой пароль.', self.cancel_keyboard())
                return
            encoded = await asyncio.to_thread(hash_password, text)
            # Only the salted hash survives between the two user messages.
            self.password_changes[chat_id] = replace(state, stage='repeat', new_hash=encoded)
            await self.sender.send_chat(chat_id, 'Повторите новый пароль для подтверждения.', self.cancel_keyboard())
            return
        if not await self._password_matches(text, state.new_hash):
            self.password_changes[chat_id] = replace(state, stage='new', new_hash=None)
            await self.sender.send_chat(chat_id, 'Пароли не совпали. Введите новый пароль заново.', self.cancel_keyboard())
            return
        if not self.store.set_password_hash(
            state.new_hash, expected_hash=state.original_hash, keep_admin_chat=chat_id,
        ):
            self.password_changes.pop(chat_id, None)
            await self.sender.send_chat(chat_id, 'Пароль уже был изменён другим действием. Начните смену заново с текущим паролем.', self.keyboard())
            return
        self.password_changes.clear()
        self.pending_clears.clear()
        self.views.clear()
        self.awaiting_password.clear()
        await self.sender.send_chat(
            chat_id, 'Пароль изменён и сохранён. Ваш доступ сохранён. '
            'Остальным администраторам нужно снова выполнить /start и войти с новым паролем. '
            'Передайте его нужным сотрудникам защищённым способом.', self.keyboard(),
        )

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
        button = text.strip() if isinstance(text, str) else ''
        command = BUTTON_COMMANDS.get(button, command)
        is_admin = self.store.is_admin(chat_id)
        if command == '/start':
            self.pending_clears.pop(chat_id, None)
            self.password_changes.pop(chat_id, None)
            self.views.pop(chat_id, None)
            if is_admin:
                self.store.touch_admin(chat_id, profile=profile)
                await self.sender.send_chat(chat_id, 'Вы авторизованы как администратор.\n\n' + self.help_text(), self.keyboard())
            else:
                self.awaiting_password.add(chat_id)
                await self.sender.send_chat(chat_id, 'Введите пароль администратора одним сообщением.\n\n' + self.help_text(), self.entry_keyboard())
            return
        if not is_admin and chat_id in self.awaiting_password:
            verified_hash = self.store.password_hash()
            if await self._password_matches(text, verified_hash):
                # A server-side reset may run while the KDF is in its worker
                # thread. The password check and chat registration must agree
                # on the same current hash in one atomic SQLite statement.
                if self.store.add_admin_if_password_current(
                    chat_id, user_id, expected_hash=verified_hash, **profile,
                ):
                    self.awaiting_password.discard(chat_id)
                    await self.sender.send_chat(chat_id, 'Пароль принят. Вы авторизованы как администратор.\n\n' + self.help_text(), self.keyboard())
                    return
        if not is_admin:
            self.pending_clears.pop(chat_id, None)
            self.views.pop(chat_id, None)
            self.password_changes.pop(chat_id, None)
            if command == '/help':
                await self.sender.send_chat(chat_id, 'Сначала нажмите «Войти» или выполните /start и введите пароль администратора.\n\n' + self.help_text(), self.entry_keyboard())
            else:
                await self.sender.send_chat(chat_id, 'Сначала нажмите «Войти» или выполните /start и введите пароль администратора.', self.entry_keyboard())
            return
        self.store.touch_admin(chat_id, profile=profile)
        controls = {'/start', '/help', '/admins', '/week', '/history', '/all', '/logout',
                    '/clear', '/confirm_clear', '/cancel', '/password', '/next', '/prev'}
        is_control = button in BUTTON_COMMANDS or (button.startswith('/') and command in controls) or button == 'week'
        if chat_id in self.password_changes:
            if not is_control:
                self.pending_clears.pop(chat_id, None)
                await self._password_step(chat_id, text)
                return
            self.password_changes.pop(chat_id, None)
        if command not in ('/confirm_clear', '/clear'):
            # Switching tasks abandons any destructive confirmation prompt.
            self.pending_clears.pop(chat_id, None)
        if command == '/logout':
            self.awaiting_password.discard(chat_id)
            self.views.pop(chat_id, None)
            self.store.remove_admin(chat_id)
            await self.sender.send_chat(
                chat_id, 'Вы вышли из администраторов. Для входа нажмите «Войти» или выполните /start и введите пароль.',
                self.entry_keyboard(),
            )
        elif command == '/help':
            self.views.pop(chat_id, None)
            await self.sender.send_chat(chat_id, self.help_text(), self.keyboard())
        elif command == '/admins':
            messages = self._admin_messages()
            for index, result in enumerate(messages):
                await self.sender.send_chat(
                    chat_id, result, self.keyboard() if index == len(messages) - 1 else None,
                    parse_mode='HTML',
                )
        elif command in ('/week', 'week', '/history', '/all'):
            since = time.time() - 7 * 86400 if command in ('/week', 'week') else None
            await self._show_leads(chat_id, LeadView(self.store.history_snapshot(), since=since))
        elif command in ('/prev', '/next'):
            view = self.views.get(chat_id)
            if view is None:
                await self.sender.send_chat(chat_id, 'Сначала откройте «Вся история» или «Заявки за неделю».', self.keyboard())
            else:
                offset = view.offset + (PAGE_SIZE if command == '/next' else -PAGE_SIZE)
                await self._show_leads(chat_id, replace(view, offset=offset))
        elif command == '/clear':
            await self._request_clear(chat_id)
        elif command == '/password':
            await self._request_password_change(chat_id)
        elif command == '/confirm_clear':
            await self._confirm_clear(chat_id)
        elif command == '/cancel':
            await self.sender.send_chat(chat_id, 'Действие отменено. Выберите нужную кнопку.', self.keyboard())
        else:
            await self.sender.send_chat(chat_id, 'Выберите действие кнопкой в меню. Подробное описание — «Помощь» или /help.', self.keyboard())

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
        while True:
            try:
                ok = await self.poll_once()
                if not ok:
                    await asyncio.sleep(5)
            except Exception:
                await asyncio.sleep(5)
