"""Small durable outbox. All operations run on the single service event loop."""
import sqlite3
import time
from pathlib import Path


_PASSWORD_UNSET = object()


def _remove_admin(db, chat_id: str, now: float):
    """Revoke one chat inside a transaction owned by the caller."""
    db.execute('DELETE FROM bot_admins WHERE chat_id=?', (chat_id,))
    db.execute(
        "UPDATE lead_deliveries SET state='cancelled', next_attempt=0, "
        "error_code='admin_logged_out', sent_at=NULL "
        "WHERE chat_id=? AND state IN ('pending','sending')", (chat_id,)
    )
    # Keep successful delivery records and preserve the independent history.
    db.execute(
        "UPDATE leads SET state='cancelled', next_attempt=0, error_code='admin_logged_out', sent_at=? "
        "WHERE state NOT IN ('sent','cancelled') "
        "AND EXISTS (SELECT 1 FROM lead_deliveries d WHERE d.request_id=leads.request_id AND d.state='cancelled') "
        "AND NOT EXISTS (SELECT 1 FROM lead_deliveries d WHERE d.request_id=leads.request_id AND d.state NOT IN ('sent','cancelled'))",
        (now,),
    )


def revoke_admins(db, *, keep_chat: str | int | None = None) -> int:
    """Revoke existing admins without beginning or committing a transaction.

    Password changes and operator resets wrap this together with the hash
    update. Calling Store startup recovery here would disturb active sends.
    """
    if keep_chat is None:
        rows = db.execute('SELECT chat_id FROM bot_admins ORDER BY chat_id').fetchall()
    else:
        rows = db.execute('SELECT chat_id FROM bot_admins WHERE chat_id<>? ORDER BY chat_id',
                          (str(keep_chat),)).fetchall()
    now = time.time()
    for row in rows:
        _remove_admin(db, str(row[0]), now)
    return len(rows)


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
                error_code TEXT NOT NULL DEFAULT '', sent_at REAL,
                delivered_to TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS delivery_queue ON leads(state, next_attempt);
            CREATE TABLE IF NOT EXISTS lead_deliveries (
                request_id TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                next_attempt REAL NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                error_code TEXT NOT NULL DEFAULT '',
                sent_at REAL,
                PRIMARY KEY(request_id, chat_id)
            );
            CREATE INDEX IF NOT EXISTS lead_delivery_queue
                ON lead_deliveries(request_id, state, next_attempt);
            CREATE TABLE IF NOT EXISTS bot_admins (
                chat_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                added_at REAL NOT NULL,
                last_seen REAL NOT NULL,
                first_name TEXT NOT NULL DEFAULT '',
                last_name TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS lead_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                phone TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS lead_history_order
                ON lead_history(created_at DESC, id DESC);
        ''')
        # The delivery result may be unknown after a crash; retry it after the
        # same five-minute delay used for other unconfirmed sends. Existing
        # lead_deliveries rows are recovered alongside their parent lead.
        recovery_time = time.time() + 300
        with self.db:
            columns = {row['name'] for row in self.db.execute('PRAGMA table_info(leads)')}
            if 'delivered_to' not in columns:
                self.db.execute("ALTER TABLE leads ADD COLUMN delivered_to TEXT NOT NULL DEFAULT ''")
            admin_columns = {row['name'] for row in self.db.execute('PRAGMA table_info(bot_admins)')}
            for column in ('first_name', 'last_name', 'username'):
                if column not in admin_columns:
                    self.db.execute(f"ALTER TABLE bot_admins ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
            self.db.execute("UPDATE leads SET state='pending', next_attempt=?, error_code='restart_during_send' WHERE state='sending'",
                            (recovery_time,))
            self.db.execute("UPDATE lead_deliveries SET state='pending', next_attempt=?, error_code='restart_during_send' WHERE state='sending'",
                            (recovery_time,))
            # Backfill exactly once, in the same transaction as the marker.
            # Clearing the visible history must remain effective after restart,
            # even while its independent outbox rows are still being delivered.
            initialized = self.db.execute(
                "SELECT 1 FROM bot_state WHERE key='lead_history_initialized'"
            ).fetchone()
            if not initialized:
                self.db.execute(
                    'INSERT OR IGNORE INTO lead_history(request_id,phone,created_at) '
                    'SELECT request_id,phone,created_at FROM leads ORDER BY created_at,request_id'
                )
                self.db.execute(
                    "INSERT INTO bot_state(key,value) VALUES('lead_history_initialized','1')"
                )

    def close(self):
        self.db.close()

    def password_hash(self) -> str | None:
        """Read on every authentication so an operator reset applies live."""
        row = self.db.execute(
            "SELECT value FROM bot_state WHERE key='admin_password_hash'"
        ).fetchone()
        return str(row['value']) if row else None

    def set_password_hash(self, encoded: str, *, expected_hash=_PASSWORD_UNSET,
                          keep_admin_chat=_PASSWORD_UNSET) -> bool:
        """Atomically replace a verified password and optionally revoke admins.

        Omitting keep_admin_chat preserves registrations; a chat ID keeps only
        that administrator, and explicit None revokes every administrator.
        """
        with self.db:
            if expected_hash is None:
                changed = bool(self.db.execute(
                    "INSERT INTO bot_state(key,value) VALUES('admin_password_hash',?) "
                    'ON CONFLICT(key) DO NOTHING', (encoded,)
                ).rowcount)
            elif expected_hash is not _PASSWORD_UNSET:
                changed = bool(self.db.execute(
                    "UPDATE bot_state SET value=? WHERE key='admin_password_hash' AND value=?",
                    (encoded, expected_hash)
                ).rowcount)
            else:
                self.db.execute(
                    "INSERT INTO bot_state(key,value) VALUES('admin_password_hash',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (encoded,)
                )
                changed = True
            if changed and keep_admin_chat is not _PASSWORD_UNSET:
                revoke_admins(self.db, keep_chat=keep_admin_chat)
            return changed

    def add_admin(self, chat_id: str | int, user_id: str | int | None = None,
                  now: float | None = None, *, first_name: str = '',
                  last_name: str = '', username: str = ''):
        """Remember a private chat that authenticated with the bot password.

        Telegram private chat IDs are stable and are the only destination key we
        need.  The user ID is kept separately for auditability and future group
        support, but group chats are never added by the bot.
        """
        chat_id = str(chat_id)
        user_id = chat_id if user_id is None else str(user_id)
        now = time.time() if now is None else now
        with self.db:
            self.db.execute(
                '''INSERT INTO bot_admins(chat_id,user_id,added_at,last_seen,first_name,last_name,username)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(chat_id) DO UPDATE SET user_id=excluded.user_id,
                   last_seen=excluded.last_seen, first_name=excluded.first_name,
                   last_name=excluded.last_name, username=excluded.username''',
                (chat_id, user_id, now, now, first_name, last_name, username),
            )

    def add_admin_if_password_current(self, chat_id: str | int,
                                      user_id: str | int | None = None, *,
                                      expected_hash: str | None, first_name: str = '',
                                      last_name: str = '', username: str = '') -> bool:
        """Register only if the verified password survived asynchronous work.

        The condition and registration are one SQLite write, so a concurrent
        operator reset cannot reauthorize someone who verified the old hash.
        A missing hash matches only bootstrap authentication (expected None).
        """
        chat_id = str(chat_id)
        user_id = chat_id if user_id is None else str(user_id)
        now = time.time()
        with self.db:
            return bool(self.db.execute(
                '''INSERT INTO bot_admins(chat_id,user_id,added_at,last_seen,first_name,last_name,username)
                   SELECT ?,?,?,?,?,?,?
                   WHERE (SELECT value FROM bot_state WHERE key='admin_password_hash') IS ?
                   ON CONFLICT(chat_id) DO UPDATE SET user_id=excluded.user_id,
                   last_seen=excluded.last_seen, first_name=excluded.first_name,
                   last_name=excluded.last_name, username=excluded.username''',
                (chat_id, user_id, now, now, first_name, last_name, username, expected_hash),
            ).rowcount)

    def touch_admin(self, chat_id: str | int, now: float | None = None, *,
                    profile: dict | None = None):
        now = time.time() if now is None else now
        with self.db:
            if profile is None:
                self.db.execute('UPDATE bot_admins SET last_seen=? WHERE chat_id=?',
                                (now, str(chat_id)))
            else:
                self.db.execute(
                    'UPDATE bot_admins SET last_seen=?, first_name=?, last_name=?, username=? '
                    'WHERE chat_id=?',
                    (now, profile['first_name'], profile['last_name'], profile['username'], str(chat_id)),
                )

    def remove_admin(self, chat_id: str | int):
        """Revoke a chat and cancel unconfirmed deliveries from its snapshots."""
        with self.db:
            _remove_admin(self.db, str(chat_id), time.time())

    def is_admin(self, chat_id: str | int) -> bool:
        return self.db.execute('SELECT 1 FROM bot_admins WHERE chat_id=?',
                               (str(chat_id),)).fetchone() is not None

    def admin_chats(self) -> list[str]:
        """Return only private chats that authenticated with the bot password."""
        rows = self.db.execute('SELECT chat_id FROM bot_admins ORDER BY added_at').fetchall()
        return [str(row['chat_id']) for row in rows]

    def admins(self):
        return [dict(row) for row in self.db.execute(
            'SELECT chat_id,user_id,added_at,first_name,last_name,username '
            'FROM bot_admins ORDER BY added_at,chat_id'
        )]

    def update_offset(self) -> int:
        row = self.db.execute("SELECT value FROM bot_state WHERE key='telegram_offset'").fetchone()
        try:
            return int(row['value']) if row else 0
        except (TypeError, ValueError):
            return 0

    def save_offset(self, offset: int):
        with self.db:
            self.db.execute(
                "INSERT INTO bot_state(key,value) VALUES('telegram_offset',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(int(offset)),)
            )

    def week_leads(self, now: float | None = None, days: int = 7):
        now = time.time() if now is None else now
        return self.history_leads(
            through_id=self.history_snapshot(), since=now - days * 86400, limit=1000
        )

    def history_snapshot(self) -> int:
        """Capture a stable upper bound for a listing or clear confirmation."""
        return int(self.db.execute('SELECT COALESCE(MAX(id),0) FROM lead_history').fetchone()[0])

    def history_count(self, *, through_id: int, since: float | None = None) -> int:
        query = 'SELECT COUNT(*) FROM lead_history WHERE id<=?'
        values = [through_id]
        if since is not None:
            query += ' AND created_at>=?'
            values.append(since)
        return int(self.db.execute(query, values).fetchone()[0])

    def history_leads(self, *, through_id: int, since: float | None = None,
                      offset: int = 0, limit: int = 25) -> list[dict]:
        """Read a bounded page; new arrivals never shift this snapshot's pages."""
        if type(offset) is not int or offset < 0:
            raise ValueError('History offset must be a nonnegative integer')
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('History page size must be between 1 and 1000')
        query = 'SELECT id,request_id,phone,created_at FROM lead_history WHERE id<=?'
        values = [through_id]
        if since is not None:
            query += ' AND created_at>=?'
            values.append(since)
        query += ' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?'
        values.extend((limit, offset))
        rows = self.db.execute(query, values).fetchall()
        return [dict(row) for row in rows]

    def clear_history(self, through_id: int) -> int:
        """Clear only confirmed history; preserve new arrivals and the outbox."""
        with self.db:
            return self.db.execute('DELETE FROM lead_history WHERE id<=?', (through_id,)).rowcount

    def due_deliveries(self, request_id: str, now: float | None = None):
        now = time.time() if now is None else now
        rows = self.db.execute(
            "SELECT * FROM lead_deliveries WHERE request_id=? AND state='pending' "
            "AND next_attempt<=? ORDER BY chat_id", (request_id, now)
        ).fetchall()
        return [dict(row) for row in rows]

    def claim_delivery(self, request_id: str, chat_id: str, now: float | None = None):
        now = time.time() if now is None else now
        with self.db:
            row = self.db.execute(
                "SELECT * FROM lead_deliveries WHERE request_id=? AND chat_id=? "
                "AND state='pending' AND next_attempt<=?",
                (request_id, str(chat_id), now),
            ).fetchone()
            if not row:
                return None
            self.db.execute(
                'UPDATE lead_deliveries SET state=\'sending\', attempts=attempts+1 '
                'WHERE request_id=? AND chat_id=?', (request_id, str(chat_id)),
            )
        return dict(row)

    def finish_delivery(self, request_id: str, chat_id: str, state: str = 'pending',
                        delay: float = 0, error_code: str = ''):
        if state not in ('sent', 'pending'):
            raise ValueError('Invalid delivery state')
        now = time.time()
        with self.db:
            existing = self.db.execute(
                'SELECT state FROM lead_deliveries WHERE request_id=? AND chat_id=?',
                (request_id, str(chat_id)),
            ).fetchone()
            if not existing or (existing['state'] in ('sent','cancelled') and state != 'sent'):
                return
            self.db.execute(
                'UPDATE lead_deliveries SET state=?, next_attempt=?, error_code=?, sent_at=? '
                'WHERE request_id=? AND chat_id=?',
                (state, now + delay, error_code, now if state == 'sent' else None,
                 request_id, str(chat_id)),
            )
            if state == 'sent':
                row = self.db.execute('SELECT delivered_to FROM leads WHERE request_id=?',
                                      (request_id,)).fetchone()
                delivered = [value for value in (row['delivered_to'] if row else '').split(',') if value]
                if str(chat_id) not in delivered:
                    delivered.append(str(chat_id))
                    self.db.execute('UPDATE leads SET delivered_to=? WHERE request_id=?',
                                    (','.join(delivered), request_id))

    def all_delivered(self, request_id: str) -> bool:
        row = self.db.execute(
            "SELECT COUNT(*) AS total, SUM(state='sent') AS sent "
            'FROM lead_deliveries WHERE request_id=?', (request_id,)
        ).fetchone()
        return bool(row and row['total'] and row['total'] == (row['sent'] or 0))

    def all_resolved(self, request_id: str) -> bool:
        row = self.db.execute(
            "SELECT COUNT(*) AS total, SUM(state IN ('sent','cancelled')) AS resolved "
            'FROM lead_deliveries WHERE request_id=?', (request_id,)
        ).fetchone()
        return bool(row and row['total'] and row['total'] == (row['resolved'] or 0))

    def next_delivery_delay(self, request_id: str, now: float | None = None,
                            default: float = 300) -> float:
        now = time.time() if now is None else now
        row = self.db.execute(
            "SELECT MIN(next_attempt) AS next_attempt FROM lead_deliveries "
            "WHERE request_id=? AND state IN ('pending','sending')", (request_id,)
        ).fetchone()
        if not row or row['next_attempt'] is None:
            return default
        return max(1, row['next_attempt'] - now)

    def delivery_rows(self, request_id: str):
        rows = self.db.execute(
            'SELECT * FROM lead_deliveries WHERE request_id=? ORDER BY chat_id',
            (request_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def delivered_chats(self, request_id: str) -> list[str]:
        row = self.db.execute('SELECT delivered_to FROM leads WHERE request_id=?',
                              (request_id,)).fetchone()
        return [value for value in (row['delivered_to'] if row else '').split(',') if value]

    def get(self, request_id: str):
        row = self.db.execute('SELECT * FROM leads WHERE request_id=?', (request_id,)).fetchone()
        return dict(row) if row else None

    def accept(self, request_id: str, phone: str, now: float | None = None,
               admin_chats=()):
        now = time.time() if now is None else now
        chats = sorted({str(chat_id) for chat_id in (admin_chats or ()) if str(chat_id)})
        with self.db:
            existing = self.get(request_id)
            if existing:
                if existing['phone'] != phone:
                    raise Conflict()
                return 'existing'
            if self.db.execute("SELECT COUNT(*) FROM leads WHERE state NOT IN ('sent','cancelled')").fetchone()[0] >= 1000:
                raise Capacity()
            self.db.execute(
                'INSERT INTO leads(request_id,phone,created_at,delivered_to) VALUES (?,?,?,?)',
                (request_id, phone, now, ''),
            )
            # The archive records acceptance, not delivery attempts. A retry of
            # an existing outbox row must never restore a cleared history entry.
            self.db.execute(
                'INSERT OR IGNORE INTO lead_history(request_id,phone,created_at) VALUES (?,?,?)',
                (request_id, phone, now),
            )
            self.db.executemany(
                'INSERT OR IGNORE INTO lead_deliveries(request_id,chat_id) VALUES (?,?)',
                ((request_id, chat_id) for chat_id in chats),
            )
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
        if state not in ('sent', 'cancelled', 'pending', 'unknown', 'blocked'):
            raise ValueError('Invalid outbox state')
        now = time.time()
        with self.db:
            # Logout may have resolved a lead while its completion commit was
            # waiting to be retried. Never put cancelled deliveries back in work.
            if state in ('pending', 'sent') and self.all_resolved(request_id):
                if not self.all_delivered(request_id):
                    state, delay, error_code = 'cancelled', 0, 'admin_logged_out'
            self.db.execute('UPDATE leads SET state=?, next_attempt=?, error_code=?, sent_at=? WHERE request_id=?',
                            (state, now + delay, error_code, now if state in ('sent','cancelled') else None, request_id))

    def cleanup(self, retention_days: int):
        with self.db:
            self.db.execute(
                "DELETE FROM lead_deliveries WHERE request_id IN "
                "(SELECT request_id FROM leads WHERE state IN ('sent','cancelled') AND sent_at<?)",
                (time.time() - retention_days * 86400,),
            )
            self.db.execute("DELETE FROM leads WHERE state IN ('sent','cancelled') AND sent_at<?", (time.time() - retention_days * 86400,))
        self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')

    def unresolved(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM leads WHERE state NOT IN ('sent','cancelled') ORDER BY created_at LIMIT 1000")]
