"""Small durable outbox. All operations run on the single service event loop."""
import sqlite3
import time
from pathlib import Path


class Conflict(Exception):
    pass


class Capacity(Exception):
    pass


class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=5, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA secure_delete=ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS leads (
                request_id TEXT PRIMARY KEY, phone TEXT NOT NULL,
                created_at REAL NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                next_attempt REAL NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
                error_code TEXT NOT NULL DEFAULT '', sent_at REAL
            );
            CREATE INDEX IF NOT EXISTS delivery_queue ON leads(state, next_attempt);
        ''')
        # A process can die after Telegram accepted a request but before our commit.
        with self.db:
            self.db.execute("UPDATE leads SET state='unknown', error_code='restart_during_send' WHERE state='sending'")

    def close(self):
        self.db.close()

    def get(self, request_id: str):
        row = self.db.execute('SELECT * FROM leads WHERE request_id=?', (request_id,)).fetchone()
        return dict(row) if row else None

    def accept(self, request_id: str, phone: str, now: float | None = None):
        now = time.time() if now is None else now
        with self.db:
            existing = self.get(request_id)
            if existing:
                if existing['phone'] != phone:
                    raise Conflict()
                return 'existing'
            if self.db.execute("SELECT COUNT(*) FROM leads WHERE state!='sent'").fetchone()[0] >= 1000:
                raise Capacity()
            self.db.execute('INSERT INTO leads(request_id,phone,created_at) VALUES (?,?,?)', (request_id, phone, now))
        return 'created'

    def claim(self, now: float | None = None):
        now = time.time() if now is None else now
        with self.db:
            row = self.db.execute("SELECT * FROM leads WHERE state='pending' AND next_attempt<=? ORDER BY created_at LIMIT 1", (now,)).fetchone()
            if not row:
                return None
            self.db.execute("UPDATE leads SET state='sending', attempts=attempts+1 WHERE request_id=?", (row['request_id'],))
        return dict(row)

    def finish(self, request_id: str, state: str, delay: float = 0, error_code: str = ''):
        if state not in ('sent', 'pending', 'unknown', 'blocked'):
            raise ValueError('Invalid outbox state')
        now = time.time()
        with self.db:
            self.db.execute('UPDATE leads SET state=?, next_attempt=?, error_code=?, sent_at=? WHERE request_id=?',
                            (state, now + delay, error_code, now if state == 'sent' else None, request_id))

    def cleanup(self, retention_days: int):
        with self.db:
            self.db.execute("DELETE FROM leads WHERE state='sent' AND sent_at<?", (time.time() - retention_days * 86400,))
        self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')

    def unresolved(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM leads WHERE state!='sent' ORDER BY created_at LIMIT 1000")]
