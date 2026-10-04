"""Telegram responses are never logged: API URLs contain credentials."""
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx


class TelegramSender:
    def __init__(self, settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    async def send(self, row):
        date = datetime.fromtimestamp(row['created_at'], ZoneInfo('Europe/Prague')).strftime('%d.%m.%Y %H:%M:%S %Z')
        text = f"Новая заявка ART PROJECT\nДата: {date} (Europe/Prague)\nТелефон: {row['phone']}"
        try:
            response = await self.client.post(
                f'https://api.telegram.org/bot{self.settings.telegram_token}/sendMessage',
                json={'chat_id': self.settings.telegram_chat_id, 'text': text},
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            return 'pending', self.settings.retry_seconds, 'connection_unavailable'
        except httpx.HTTPError:
            # Read/write timeouts may happen after delivery. Do not blindly retry.
            return 'unknown', 0, 'delivery_unknown'
        if response.status_code >= 500:
            return 'unknown', 0, 'telegram_server_error'
        try:
            data = response.json()
        except ValueError:
            return 'unknown', 0, 'invalid_telegram_response'
        if not isinstance(data, dict):
            return 'unknown', 0, 'invalid_telegram_response'
        if response.status_code == 200 and data.get('ok') is True:
            if isinstance(data.get('result'), dict) and type(data['result'].get('message_id')) is int:
                return 'sent', 0, ''
            return 'unknown', 0, 'invalid_telegram_response'
        if data.get('ok') is False and data.get('error_code') == 429:
            parameters = data.get('parameters')
            retry = parameters.get('retry_after', self.settings.retry_seconds) if isinstance(parameters, dict) else self.settings.retry_seconds
            if type(retry) is not int:
                retry = self.settings.retry_seconds
            return 'pending', max(1, min(retry, 86400)), 'telegram_rate_limited'
        if data.get('ok') is False and type(data.get('error_code')) is int and 400 <= data['error_code'] < 500:
            return 'blocked', 0, f"telegram_{data['error_code']}"
        return 'unknown', 0, 'delivery_unknown'
