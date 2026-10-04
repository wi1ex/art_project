import asyncio
import ipaddress
import json
import logging
import os
import re
import sqlite3
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

import httpx
import maxminddb
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.storage import Capacity, Conflict, Store
from backend.telegram import TelegramSender
from backend.geoip import CountryLookup

logger = logging.getLogger('leads')
# httpx info logging contains the full bot-token URL.
logging.getLogger('httpx').setLevel(logging.CRITICAL)
logging.getLogger('httpcore').setLevel(logging.CRITICAL)


@dataclass(frozen=True)
class Settings:
    enabled: bool = False
    telegram_token: str = ''
    telegram_chat_id: str = ''
    allowed_origins: tuple[str, ...] = ()
    database_path: str = '/data/leads.sqlite3'
    retention_days: int = 7
    retry_seconds: int = 30
    start_worker: bool = True
    geoip_database_path: str = '/geoip/country.mmdb'

    @classmethod
    def from_env(cls):
        return cls(
            enabled=os.environ.get('LEADS_ENABLED', '').lower() == 'true',
            telegram_token=os.environ.get('TELEGRAM_BOT_TOKEN', '').strip(),
            telegram_chat_id=os.environ.get('TELEGRAM_CHAT_ID', '').strip(),
            allowed_origins=tuple(value.strip().rstrip('/') for value in os.environ.get('LEADS_ALLOWED_ORIGINS', '').split(',') if value.strip()),
            database_path=os.environ.get('DATABASE_PATH', '/data/leads.sqlite3'),
            geoip_database_path=os.environ.get('GEOIP_DATABASE_PATH', '/geoip/country.mmdb'),
        )

    @property
    def accepting(self):
        return bool(self.enabled and self.telegram_token and self.telegram_chat_id and self.allowed_origins)


class RateLimit:
    def __init__(self):
        self.clients: dict[str, deque] = {}
        self.global_requests = deque()

    def allow(self, ip: str):
        now = time.monotonic()
        for key in list(self.clients):
            times = self.clients[key]
            while times and times[0] <= now - 600:
                times.popleft()
            if not times:
                del self.clients[key]
        while self.global_requests and self.global_requests[0] <= now - 60:
            self.global_requests.popleft()
        times = self.clients.get(ip, deque())
        if len(times) >= 3 or len(self.global_requests) >= 20 or len(self.clients) >= 2000:
            return False
        times.append(now)
        self.clients[ip] = times
        self.global_requests.append(now)
        return True


class Dispatcher:
    def __init__(self, store, sender, settings):
        self.store, self.sender, self.settings = store, sender, settings
        self.lock = asyncio.Lock()
        self.uncommitted = None
        self.storage_failed = False

    def commit_result(self):
        request_id, state, delay, code = self.uncommitted
        try:
            self.store.finish(request_id, state, delay, code)
        except sqlite3.Error:
            self.storage_failed = True
            raise
        self.storage_failed = False
        self.uncommitted = None
        logger.log(logging.INFO if state == 'sent' else logging.WARNING,
                   'Lead %s: %s (%s)', request_id, state, code)

    async def dispatch_once(self):
        async with self.lock:
            # Retrying a failed SQLite completion must never re-send to Telegram.
            if self.uncommitted:
                self.commit_result()
                return True
            row = self.store.claim()
            if not row:
                return False
            try:
                state, delay, code = await self.sender.send(row)
            except Exception:
                state, delay, code = 'unknown', 0, 'unexpected_delivery_error'
            # Exponential reconnect backoff, bounded to fifteen minutes.
            if state == 'pending' and code == 'connection_unavailable':
                delay = min(900, delay * 2 ** min(row['attempts'], 5))
            self.uncommitted = row['request_id'], state, delay, code
            self.commit_result()
            return True

    async def run(self):
        last_cleanup = 0.0
        while True:
            try:
                if time.monotonic() - last_cleanup > 3600:
                    self.store.cleanup(self.settings.retention_days)
                    last_cleanup = time.monotonic()
                await self.dispatch_once()
            except sqlite3.Error:
                logger.error('Outbox storage error; operator action required')
            await asyncio.sleep(1.1)


def normalize_phone(value):
    if not isinstance(value, str) or len(value) > 64 or not re.fullmatch(r'[+0-9 ()\-]+', value):
        return None
    phone = re.sub(r'[ ()\-]', '', value)
    return phone if re.fullmatch(r'\+[1-9][0-9]{7,14}', phone) else None


def create_app(settings: Settings | None = None, transport=None, country_lookup=None):
    settings = settings or Settings.from_env()
    limiter = RateLimit()

    @asynccontextmanager
    async def lifespan(app):
        store = Store(settings.database_path)
        lookup = country_lookup if country_lookup is not None else CountryLookup(settings.geoip_database_path)
        app.state.country_lookup = lookup
        async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(10, connect=5),
                                    follow_redirects=False, trust_env=False) as client:
            dispatcher = Dispatcher(store, TelegramSender(settings, client), settings)
            app.state.store, app.state.dispatcher = store, dispatcher
            task = asyncio.create_task(dispatcher.run()) if settings.accepting and settings.start_worker else None
            try:
                yield
            finally:
                if task:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                store.close()
                if country_lookup is None:
                    lookup.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def error(code, status):
        return JSONResponse({'error': code}, status_code=status,
                            headers={'Cache-Control': 'no-store', **({'Retry-After': '600'} if status == 429 else {})})

    @app.get('/locale')
    async def locale(request: Request):
        address = request.headers.get('x-real-ip', request.client.host if request.client else '')
        country = None
        try:
            parsed = ipaddress.ip_address(address)
            if parsed.is_global:
                country = app.state.country_lookup(str(parsed))
        except (ValueError, OSError, RuntimeError, maxminddb.InvalidDatabaseError):
            pass
        return JSONResponse({'lang': {'CZ': 'cs', 'RU': 'ru'}.get(country, 'en')},
                            headers={'Cache-Control': 'private, no-store'})

    @app.get('/healthz')
    async def health():
        try:
            app.state.store.db.execute('SELECT 1').fetchone()
        except sqlite3.Error:
            return error('unavailable', 503)
        return JSONResponse({'status': 'ok', 'accepting_leads': settings.accepting and not app.state.dispatcher.storage_failed}, headers={'Cache-Control': 'no-store'})

    @app.post('/leads')
    async def lead(request: Request):
        if not settings.accepting or app.state.dispatcher.storage_failed:
            return error('unavailable', 503)
        if request.headers.get('origin') not in settings.allowed_origins:
            return error('forbidden', 403)
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            return error('invalid_request', 422)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 2048:
                return error('invalid_request', 413)
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError, RecursionError):
            return error('invalid_request', 422)
        if not isinstance(data, dict) or set(data) != {'phone', 'consent', 'request_id', 'website'}:
            return error('invalid_request', 422)
        if data['consent'] is not True:
            return error('consent_required', 422)
        if data['website'] != '':
            return error('invalid_request', 422)
        phone = normalize_phone(data['phone'])
        if not phone:
            return error('invalid_phone', 422)
        try:
            if not isinstance(data['request_id'], str):
                raise ValueError()
            request_id = str(UUID(data['request_id']))
        except (ValueError, AttributeError):
            return error('invalid_request', 422)
        try:
            existing = app.state.store.get(request_id)
            if existing:
                if existing['phone'] != phone:
                    return error('conflict', 409)
            else:
                # Nginx overwrites this header. The service port must stay private.
                ip = request.headers.get('x-real-ip', request.client.host if request.client else 'unknown')
                try:
                    ip = str(ipaddress.ip_address(ip))
                except ValueError:
                    ip = 'unknown'
                if not limiter.allow(ip):
                    return error('rate_limited', 429)
                app.state.store.accept(request_id, phone)
        except Conflict:
            return error('conflict', 409)
        except (Capacity, sqlite3.Error):
            return error('unavailable', 503)
        return JSONResponse({'status': 'accepted', 'request_id': request_id}, status_code=202, headers={'Cache-Control': 'no-store'})

    return app


app = create_app()
