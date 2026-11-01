import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.storage import Conflict, Store


class HistoryStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / 'leads.sqlite3')
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def reopen(self):
        self.store.close()
        self.store = Store(self.path)

    def test_completed_history_survives_outbox_cleanup_and_restart(self):
        old = time.time() - 8 * 86400
        self.store.add_admin('42')
        self.store.accept('old', '+420774411158', now=old, admin_chats=('42',))
        with patch('backend.storage.time.time', return_value=old):
            self.store.finish_delivery('old', '42', 'sent')
            self.store.finish('old', 'sent')
        self.store.cleanup(7)
        self.assertIsNone(self.store.get('old'))
        self.assertEqual(self.store.delivery_rows('old'), [])
        self.reopen()
        rows = self.store.history_leads(through_id=self.store.history_snapshot())
        self.assertEqual([(row['request_id'], row['phone'], row['created_at']) for row in rows],
                         [('old', '+420774411158', old)])
        self.assertEqual(self.store.week_leads(), [])

    def test_legacy_outbox_backfills_only_once_and_clearing_survives_restart(self):
        legacy_path = str(Path(self.directory.name) / 'legacy.sqlite3')
        with sqlite3.connect(legacy_path) as database:
            database.execute('''
                CREATE TABLE leads (
                    request_id TEXT PRIMARY KEY, phone TEXT NOT NULL,
                    created_at REAL NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                    next_attempt REAL NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT NOT NULL DEFAULT '', sent_at REAL,
                    delivered_to TEXT NOT NULL DEFAULT ''
                )
            ''')
            database.executemany(
                'INSERT INTO leads(request_id,phone,created_at) VALUES (?,?,?)',
                [('first', '+420774411158', 1000), ('second', '+420774411159', 2000)],
            )
        legacy = Store(legacy_path)
        try:
            snapshot = legacy.history_snapshot()
            self.assertEqual(legacy.history_count(through_id=snapshot), 2)
            self.assertEqual([row['request_id'] for row in legacy.history_leads(through_id=snapshot)],
                             ['second', 'first'])
            self.assertEqual(legacy.clear_history(snapshot), 2)
        finally:
            legacy.close()
        legacy = Store(legacy_path)
        try:
            self.assertEqual(legacy.history_snapshot(), 0)
            self.assertEqual(len(legacy.unresolved()), 2)
            self.assertEqual(legacy.accept('first', '+420774411158'), 'existing')
            self.assertEqual(legacy.history_count(through_id=snapshot), 0)
            legacy.accept('future', '+420774411160', now=3000)
            self.assertGreater(legacy.history_snapshot(), snapshot)
        finally:
            legacy.close()

    def test_clear_preserves_inflight_deliveries_admins_offset_and_deduplication(self):
        self.store.add_admin('42', first_name='Admin')
        self.store.add_admin('43')
        self.store.save_offset(123)
        self.store.accept('pending', '+420774411158', admin_chats=self.store.admin_chats())
        self.assertIsNotNone(self.store.claim())
        self.assertIsNotNone(self.store.claim_delivery('pending', '42'))
        admins = self.store.admins()
        self.assertEqual(self.store.clear_history(self.store.history_snapshot()), 1)
        self.assertEqual(self.store.admins(), admins)
        self.assertEqual(self.store.update_offset(), 123)
        self.assertEqual(self.store.get('pending')['state'], 'sending')
        self.assertEqual({row['chat_id']: row['state'] for row in self.store.delivery_rows('pending')},
                         {'42': 'sending', '43': 'pending'})
        self.store.finish_delivery('pending', '42', 'sent')
        self.store.finish_delivery('pending', '43', 'pending', 300, 'connection_unavailable')
        self.store.finish('pending', 'pending', 300, 'delivery_pending')
        self.assertEqual(self.store.delivered_chats('pending'), ['42'])
        self.assertEqual(self.store.accept('pending', '+420774411158'), 'existing')
        with self.assertRaises(Conflict):
            self.store.accept('pending', '+420774411159')
        self.assertEqual(self.store.history_snapshot(), 0)
        self.reopen()
        self.assertEqual(self.store.history_snapshot(), 0)
        self.assertEqual(self.store.update_offset(), 123)
        self.assertEqual(self.store.get('pending')['state'], 'pending')
        self.assertEqual(self.store.delivered_chats('pending'), ['42'])

    def test_pagination_covers_more_than_1000_equal_timestamp_entries(self):
        count = 1205
        for index in range(count):
            request_id = f'lead-{index}'
            self.store.accept(request_id, '+420774411158', now=1000)
            self.store.finish(request_id, 'sent')
        snapshot = self.store.history_snapshot()
        self.assertEqual(self.store.history_count(through_id=snapshot), count)
        first_page = self.store.history_leads(through_id=snapshot)
        # A new, backdated submission must not shift later pages of the listing.
        self.store.accept('new-after-snapshot', '+420774411159', now=1000)
        rows = first_page[:]
        for offset in range(25, count, 25):
            rows.extend(self.store.history_leads(through_id=snapshot, offset=offset))
        self.assertEqual([row['request_id'] for row in rows],
                         [f'lead-{index}' for index in reversed(range(count))])
        self.assertEqual(len({row['id'] for row in rows}), count)
        self.assertEqual(self.store.history_count(through_id=snapshot), count)
        self.assertEqual(self.store.history_count(through_id=self.store.history_snapshot()), count + 1)

    def test_confirmation_cutoff_preserves_new_entries_and_never_reuses_ids(self):
        self.store.accept('old', '+420774411158', now=2000)
        confirmed_snapshot = self.store.history_snapshot()
        self.store.accept('new', '+420774411159', now=1000)
        newer_id = self.store.history_snapshot()
        self.assertGreater(newer_id, confirmed_snapshot)
        self.assertEqual(self.store.clear_history(confirmed_snapshot), 1)
        self.assertEqual([row['request_id'] for row in self.store.history_leads(through_id=newer_id)],
                         ['new'])
        self.assertEqual(self.store.accept('old', '+420774411158'), 'existing')
        self.assertEqual(self.store.clear_history(newer_id), 1)
        self.store.accept('latest', '+420774411160', now=3000)
        self.assertGreater(self.store.history_snapshot(), newer_id)
        self.assertEqual(self.store.clear_history(newer_id), 0)
        self.assertEqual(self.store.history_count(through_id=self.store.history_snapshot()), 1)

    def test_week_and_since_filters_use_the_archive_and_include_the_boundary(self):
        now = 10 * 86400
        boundary = now - 7 * 86400
        self.store.accept('older', '+420774411158', now=boundary - 1)
        self.store.accept('boundary', '+420774411159', now=boundary)
        self.store.accept('recent', '+420774411160', now=now)
        snapshot = self.store.history_snapshot()
        self.assertEqual(self.store.history_count(through_id=snapshot, since=boundary), 2)
        self.assertEqual(self.store.history_count(through_id=snapshot, since=0), 3)
        self.assertEqual([row['request_id'] for row in self.store.week_leads(now=now)],
                         ['recent', 'boundary'])
        self.assertEqual([row['request_id'] for row in self.store.history_leads(
            through_id=snapshot, since=boundary, offset=1, limit=1
        )], ['boundary'])
        self.assertEqual(self.store.history_count(through_id=0), 0)
        self.assertEqual(self.store.history_leads(through_id=0), [])

    def test_failed_archive_insert_rolls_back_acceptance(self):
        with self.store.db:
            self.store.db.execute('''
                CREATE TRIGGER reject_history BEFORE INSERT ON lead_history
                BEGIN SELECT RAISE(ABORT, 'history write failed'); END
            ''')
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.accept('failed', '+420774411158', admin_chats=('42',))
        self.assertIsNone(self.store.get('failed'))
        self.assertEqual(self.store.delivery_rows('failed'), [])
        self.assertEqual(self.store.history_snapshot(), 0)


if __name__ == '__main__':
    unittest.main()
