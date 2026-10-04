"""Operator tools. No command sends a Telegram message."""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone

import httpx

from backend.app import Settings


def telegram_chats(settings):
    if not settings.telegram_token:
        raise ValueError('TELEGRAM_BOT_TOKEN is not configured')
    try:
        with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
            response = client.get(f'https://api.telegram.org/bot{settings.telegram_token}/getUpdates', params={'timeout': 0})
        data = response.json()
    except (httpx.HTTPError, ValueError):
        raise ValueError('Could not read Telegram updates; check network and bot token') from None
    if response.status_code != 200 or not isinstance(data, dict) or data.get('ok') is not True:
        raise ValueError('Telegram rejected getUpdates; check token and that no webhook/poller is running')
    updates = data.get('result')
    if not isinstance(updates, list):
        raise ValueError('Invalid Telegram updates response')
    chats = {}
    for update in updates:
        if not isinstance(update, dict):
            raise ValueError('Invalid Telegram updates response')
        for key in ('message', 'my_chat_member', 'channel_post'):
            if key not in update:
                continue
            message = update[key]
            if not isinstance(message, dict) or not isinstance(message.get('chat'), dict):
                raise ValueError('Invalid Telegram updates response')
            chat = message['chat']
            if chat.get('id'):
                chats[chat['id']] = {'id': chat['id'], 'type': chat.get('type'),
                                      'name': chat.get('title') or chat.get('first_name', '')}
    print(json.dumps(list(chats.values()), ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description='Inspect Telegram recipients and undelivered leads')
    parser.add_argument('command', choices=('chats', 'pending', 'retry', 'mark-sent'))
    parser.add_argument('request_id', nargs='?')
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == 'chats':
        telegram_chats(settings)
        return
    if args.command in ('retry', 'mark-sent') and not args.request_id:
        parser.error('request_id is required')
    # Do not run Store startup recovery while the application is sending a lead.
    db = sqlite3.connect(f'file:{settings.database_path}?mode=rw', uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        if args.command == 'pending':
            rows = db.execute("SELECT request_id, phone, created_at, state, error_code, attempts FROM leads WHERE state!='sent' ORDER BY created_at LIMIT 1000")
            for row in rows:
                item = dict(row)
                item['created_at'] = datetime.fromtimestamp(item['created_at'], timezone.utc).isoformat()
                print(json.dumps(item, ensure_ascii=False))
            return
        state = 'pending' if args.command == 'retry' else 'sent'
        with db:
            changed = db.execute("UPDATE leads SET state=?, next_attempt=0, error_code='', sent_at=? WHERE request_id=? AND state IN ('unknown','blocked')",
                                 (state, datetime.now(timezone.utc).timestamp() if state == 'sent' else None, args.request_id)).rowcount
        if not changed:
            raise ValueError('Lead not found or state is not unknown/blocked; no changes made')
        print(f'{args.request_id}: {state}')
    finally:
        db.close()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except sqlite3.Error:
        print('Could not access the outbox database; check path and permissions', file=sys.stderr)
        sys.exit(1)
