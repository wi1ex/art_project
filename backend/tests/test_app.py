from __future__ import annotations

import json
import io
import logging
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timezone
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from backend.app import Settings, create_app
from backend.cli import main as cli_main, telegram_chats
from backend.storage import Capacity, Store


class BackendTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.database_path = str(Path(self.directory.name) / "leads.sqlite3")
        self.telegram_requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self.telegram_response)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def telegram_response(self, request: httpx.Request) -> httpx.Response:
        self.telegram_requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    def app(self, *, enabled: bool = True):
        return create_app(
            Settings(
                enabled=enabled,
                telegram_token="test-token",
                allowed_origins=("http://testserver",),
                database_path=self.database_path,
                start_worker=False,
            ),
            transport=self.transport,
        )

    def payload(self, **changes) -> dict:
        payload = {
            "phone": "+420 774 411 158",
            "consent": True,
            "request_id": str(uuid4()),
            "website": "",
        }
        payload.update(changes)
        return payload

    def headers(self, *, address: str = "192.0.2.10", **changes) -> dict[str, str]:
        headers = {"Origin": "http://testserver", "X-Real-IP": address}
        headers.update(changes)
        return headers

    def post(self, client: TestClient, payload: dict | None = None, **kwargs):
        # Production snapshots authenticated admin chats when accepting a lead.
        # Keep the API fixtures in the authenticated-admin state.
        client.app.state.store.add_admin("123456", "123456")
        return client.post(
            "/leads",
            json=self.payload() if payload is None else payload,
            headers=kwargs.pop("headers", self.headers()),
            **kwargs,
        )


class LeadApiTests(BackendTestCase):
    def test_disabled_service_reports_unavailable_and_does_not_send(self) -> None:
        with TestClient(self.app(enabled=False)) as client:
            health = client.get("/healthz")
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.json(), {"status": "ok", "accepting_leads": False})
            self.assertEqual(self.post(client).status_code, 503)
        self.assertEqual(self.telegram_requests, [])

    def test_enabled_service_accepts_valid_phone(self) -> None:
        payload = self.payload()
        with TestClient(self.app()) as client:
            health = client.get("/healthz")
            self.assertEqual(health.status_code, 200)
            self.assertTrue(health.json()["accepting_leads"])
            response = self.post(client, payload)
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json(), {"status": "accepted", "request_id": payload["request_id"]})
            stored = client.app.state.store.get(payload["request_id"])
            self.assertIsNotNone(stored)
            self.assertEqual(stored["phone"], "+420774411158")

    def test_validation_rejects_invalid_phone_consent_id_and_extra_fields(self) -> None:
        invalid_payloads = [
            {"phone": "420774411158"},
            {"phone": "+1234567"},
            {"phone": "+1234567890123456"},
            {"phone": "+420<script>774411158"},
            {"phone": 420774411158},
            {"phone": None},
            {"consent": False},
            {"consent": "true"},
            {"consent": 1},
            {"request_id": "not-a-uuid"},
            {"request_id": 12},
            {"name": "Unexpected field"},
            {"website": "https://spam.example"},
            {"website": None},
        ]
        with TestClient(self.app()) as client:
            for index, changes in enumerate(invalid_payloads):
                with self.subTest(changes=changes):
                    response = self.post(
                        client,
                        self.payload(**changes),
                        headers=self.headers(address=f"192.0.2.{index + 1}"),
                    )
                    self.assertEqual(response.status_code, 422)

    def test_required_phone_consent_and_id_cannot_be_omitted(self) -> None:
        with TestClient(self.app()) as client:
            for index, name in enumerate(("phone", "consent", "request_id")):
                with self.subTest(field=name):
                    payload = self.payload()
                    del payload[name]
                    response = self.post(
                        client, payload, headers=self.headers(address=f"192.0.2.{index + 1}")
                    )
                    self.assertEqual(response.status_code, 422)

    def test_origin_requires_exact_allowlisted_value(self) -> None:
        with TestClient(self.app()) as client:
            for origin in (
                None,
                "null",
                "https://example.org",
                "http://testserver.evil.example",
                "http://testserver:80",
            ):
                with self.subTest(origin=origin):
                    headers = {"X-Real-IP": "192.0.2.10"}
                    if origin is not None:
                        headers["Origin"] = origin
                    self.assertEqual(self.post(client, headers=headers).status_code, 403)
            self.assertEqual(self.post(client).status_code, 202)

    def test_large_body_is_rejected_before_it_can_be_stored(self) -> None:
        body = json.dumps(self.payload(website="x" * 2048))
        with TestClient(self.app()) as client:
            for length in (str(len(body.encode())), "1"):
                with self.subTest(content_length=length):
                    headers = self.headers(**{
                        "Content-Type": "application/json", "Content-Length": length
                    })
                    response = client.post("/leads", content=body, headers=headers)
                    self.assertEqual(response.status_code, 413)

    def test_same_request_id_and_normalized_phone_can_be_retried(self) -> None:
        payload = self.payload()
        with TestClient(self.app()) as client:
            first = self.post(client, payload)
            payload["phone"] = "+420774411158"
            second = self.post(client, payload)
            self.assertEqual(first.status_code, 202)
            self.assertEqual(second.status_code, 202)
            self.assertEqual(first.json(), second.json())

    def test_request_id_cannot_be_reused_for_another_phone(self) -> None:
        payload = self.payload()
        with TestClient(self.app()) as client:
            self.assertEqual(self.post(client, payload).status_code, 202)
            payload["phone"] = "+420774411159"
            self.assertEqual(self.post(client, payload).status_code, 409)

    def test_accepted_request_survives_application_restart(self) -> None:
        payload = self.payload()
        with TestClient(self.app()) as client:
            self.assertEqual(self.post(client, payload).status_code, 202)
            before = client.app.state.store.get(payload["request_id"])
        with TestClient(self.app()) as client:
            stored = client.app.state.store.get(payload["request_id"])
            self.assertIsNotNone(stored)
            self.assertEqual(stored["phone"], before["phone"])
            self.assertEqual(self.post(client, payload).status_code, 202)
        self.assertEqual(self.telegram_requests, [])

    def test_three_new_requests_per_ip_are_allowed_then_rate_limited(self) -> None:
        with TestClient(self.app()) as client:
            responses = [self.post(client) for _ in range(4)]
            self.assertEqual([response.status_code for response in responses], [202, 202, 202, 429])
            self.assertGreater(int(responses[-1].headers["Retry-After"]), 0)
            self.assertEqual(
                self.post(client, headers=self.headers(address="192.0.2.20")).status_code, 202
            )

    def test_retry_of_accepted_request_does_not_consume_rate_limit(self) -> None:
        payload = self.payload()
        with TestClient(self.app()) as client:
            self.assertEqual(self.post(client, payload).status_code, 202)
            self.assertEqual(self.post(client).status_code, 202)
            self.assertEqual(self.post(client).status_code, 202)
            self.assertEqual(self.post(client).status_code, 429)
            self.assertEqual(self.post(client, payload).status_code, 202)

    def test_forwarded_for_spoofing_cannot_bypass_rate_limit(self) -> None:
        with TestClient(self.app()) as client:
            responses = [
                self.post(
                    client,
                    headers=self.headers(**{"X-Forwarded-For": f"198.51.100.{index}"}),
                )
                for index in range(4)
            ]
            self.assertEqual([response.status_code for response in responses], [202, 202, 202, 429])


class LocaleTests(BackendTestCase):
    def test_locale_is_always_czech(self) -> None:
        with TestClient(self.app(enabled=False)) as client:
            for address in ("8.8.8.8", "127.0.0.1", "not-an-ip"):
                with self.subTest(address=address):
                    response = client.get("/locale", headers={"X-Real-IP": address})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json(), {"lang": "cs"})
                    self.assertIn("no-store", response.headers["Cache-Control"])


class DeliveryTests(BackendTestCase):
    def dispatch(self, client: TestClient) -> bool:
        client.app.state.store.add_admin("123456", "123456")
        return client.portal.call(client.app.state.dispatcher.dispatch_once)

    def test_accepted_lead_is_sent_once_with_phone_and_original_prague_date(self) -> None:
        request_id = str(uuid4())
        created_at = datetime(2026, 1, 15, 8, 30, tzinfo=timezone.utc).timestamp()
        with TestClient(self.app()) as client:
            client.app.state.store.accept(request_id, "+420774411158", now=created_at,
                                          admin_chats=("123456",))
            self.assertEqual(self.telegram_requests, [])
            self.assertTrue(self.dispatch(client))
            stored = client.app.state.store.get(request_id)
            self.assertEqual(stored["state"], "sent")
            self.assertIsNotNone(stored["sent_at"])
            self.assertFalse(self.dispatch(client))
        self.assertEqual(len(self.telegram_requests), 1)
        request = self.telegram_requests[0]
        self.assertEqual(request.method, "POST")
        self.assertTrue(request.url.path.endswith("/sendMessage"))
        body = json.loads(request.content)
        self.assertEqual(body["chat_id"], "123456")
        self.assertIn("+420774411158", body["text"])
        self.assertIn("15.01.2026 09:30:00 CET", body["text"])

    def test_accepted_lead_is_sent_to_every_authenticated_admin(self) -> None:
        request_id = str(uuid4())
        with TestClient(self.app()) as client:
            client.app.state.store.add_admin("42", "42")
            client.app.state.store.add_admin("43", "43")
            client.app.state.store.accept(request_id, "+420774411158", admin_chats=("42", "43"))
            self.assertTrue(client.portal.call(client.app.state.dispatcher.dispatch_once))
            self.assertEqual(client.app.state.store.get(request_id)["state"], "sent")
        self.assertEqual(
            [json.loads(request.content)["chat_id"] for request in self.telegram_requests],
            ["42", "43"],
        )

    def test_admin_authenticated_after_accept_does_not_receive_existing_lead(self) -> None:
        request_id = str(uuid4())
        with TestClient(self.app()) as client:
            store = client.app.state.store
            store.add_admin("early", "early")
            store.accept(request_id, "+420774411158", admin_chats=store.admin_chats())
            store.add_admin("late", "late")
            self.assertTrue(client.portal.call(client.app.state.dispatcher.dispatch_once))
            self.assertEqual(store.get(request_id)["state"], "sent")
            self.assertEqual(store.delivered_chats(request_id), ["early"])
            self.assertEqual([json.loads(request.content)["chat_id"] for request in self.telegram_requests], ["early"])

    def test_lead_without_admin_snapshot_stays_undelivered_for_late_admin(self) -> None:
        request_id = str(uuid4())
        with TestClient(self.app()) as client:
            store = client.app.state.store
            store.accept(request_id, "+420774411158")
            store.add_admin("late", "late")
            self.assertTrue(client.portal.call(client.app.state.dispatcher.dispatch_once))
            self.assertEqual(store.get(request_id)["state"], "pending")
            self.assertEqual(store.delivery_rows(request_id), [])
            self.assertEqual(self.telegram_requests, [])

    def test_admin_added_after_acceptance_is_not_added_to_recipient_snapshot(self) -> None:
        request_id = str(uuid4())
        with TestClient(self.app()) as client:
            client.app.state.store.add_admin("42", "42")
            client.app.state.store.accept(request_id, "+420774411158", admin_chats=("42",))
            client.app.state.store.add_admin("43", "43")
            self.assertTrue(client.portal.call(client.app.state.dispatcher.dispatch_once))
            self.assertEqual(client.app.state.store.get(request_id)["delivered_to"], "42")
            self.assertEqual(
                [json.loads(request.content)["chat_id"] for request in self.telegram_requests],
                ["42"],
            )

    def test_failed_admin_delivery_retries_only_that_admin(self) -> None:
        attempts = 0

        def response(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            self.telegram_requests.append(request)
            if attempts == 2:
                raise httpx.ConnectTimeout("temporary failure", request=request)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": attempts}})

        self.transport = httpx.MockTransport(response)
        request_id = str(uuid4())
        with TestClient(self.app()) as client:
            client.app.state.store.add_admin("42", "42")
            client.app.state.store.add_admin("43", "43")
            client.app.state.store.accept(request_id, "+420774411158", admin_chats=("42", "43"))
            self.assertTrue(client.portal.call(client.app.state.dispatcher.dispatch_once))
            self.assertEqual(client.app.state.store.get(request_id)["state"], "pending")
            with client.app.state.store.db:
                client.app.state.store.db.execute(
                    "UPDATE leads SET next_attempt=0 WHERE request_id=?", (request_id,)
                )
                client.app.state.store.db.execute(
                    "UPDATE lead_deliveries SET next_attempt=0 WHERE request_id=? AND state='pending'",
                    (request_id,),
                )
            self.assertTrue(client.portal.call(client.app.state.dispatcher.dispatch_once))
            self.assertEqual(client.app.state.store.get(request_id)["state"], "sent")
        self.assertEqual(
            [json.loads(request.content)["chat_id"] for request in self.telegram_requests],
            ["42", "43", "43"],
        )

    def test_read_timeout_stays_undelivered_for_a_five_minute_retry(self) -> None:
        def timeout(request: httpx.Request) -> httpx.Response:
            self.telegram_requests.append(request)
            raise httpx.ReadTimeout("No response", request=request)

        self.transport = httpx.MockTransport(timeout)
        payload = self.payload()
        with TestClient(self.app()) as client:
            self.assertEqual(self.post(client, payload).status_code, 202)
            self.assertTrue(self.dispatch(client))
            stored = client.app.state.store.get(payload["request_id"])
            self.assertEqual(stored["state"], "pending")
            self.assertFalse(self.dispatch(client))
        with TestClient(self.app()) as client:
            self.assertEqual(self.post(client, payload).status_code, 202)
            self.assertFalse(self.dispatch(client))
            self.assertEqual(client.app.state.store.get(payload["request_id"])["state"], "pending")
        self.assertEqual(len(self.telegram_requests), 1)

    def test_connection_failure_is_queued_with_backoff(self) -> None:
        def timeout(request: httpx.Request) -> httpx.Response:
            self.telegram_requests.append(request)
            raise httpx.ConnectTimeout("Could not connect", request=request)

        self.transport = httpx.MockTransport(timeout)
        payload = self.payload()
        with TestClient(self.app()) as client:
            self.assertEqual(self.post(client, payload).status_code, 202)
            before = time.time()
            self.assertTrue(self.dispatch(client))
            stored = client.app.state.store.get(payload["request_id"])
            self.assertEqual(stored["state"], "pending")
            self.assertGreaterEqual(stored["next_attempt"], before + 300)
            self.assertFalse(self.dispatch(client))
        self.assertEqual(len(self.telegram_requests), 1)

    def test_failed_delivery_commit_is_retried_without_sending_message_again(self) -> None:
        payload = self.payload()
        with TestClient(self.app()) as client:
            self.assertEqual(self.post(client, payload).status_code, 202)
            store = client.app.state.store
            with patch.object(store, "finish", side_effect=sqlite3.OperationalError("Temporary write failure")):
                with self.assertRaises(sqlite3.OperationalError):
                    self.dispatch(client)
                stored = store.get(payload["request_id"])
                self.assertEqual(stored["state"], "sending")
                self.assertEqual(stored["phone"], "+420774411158")
                self.assertEqual(len(self.telegram_requests), 1)
                self.assertFalse(client.get("/healthz").json()["accepting_leads"])
                self.assertEqual(self.post(client).status_code, 503)
            self.assertTrue(self.dispatch(client))
            self.assertEqual(store.get(payload["request_id"])["state"], "sent")
            self.assertTrue(client.get("/healthz").json()["accepting_leads"])
            self.assertFalse(self.dispatch(client))
        with TestClient(self.app()) as client:
            self.assertEqual(client.app.state.store.get(payload["request_id"])["state"], "sent")
        self.assertEqual(len(self.telegram_requests), 1)

    def test_failed_per_admin_commit_retries_write_before_sending_next_admin(self) -> None:
        request_id = str(uuid4())
        with TestClient(self.app()) as client:
            store = client.app.state.store
            store.add_admin('42')
            store.add_admin('43')
            store.accept(request_id, '+420774411158', admin_chats=store.admin_chats())
            original_finish = store.finish_delivery
            calls = 0

            def finish(*args):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise sqlite3.OperationalError('Temporary write failure')
                return original_finish(*args)

            with patch.object(store, 'finish_delivery', side_effect=finish):
                with self.assertRaises(sqlite3.OperationalError):
                    self.dispatch(client)
                self.assertEqual(len(self.telegram_requests), 1)
                self.assertFalse(client.get('/healthz').json()['accepting_leads'])
                self.assertTrue(self.dispatch(client))
            self.assertEqual(store.get(request_id)['state'], 'sent')
            self.assertEqual(store.delivered_chats(request_id), ['42', '43'])
            self.assertTrue(client.get('/healthz').json()['accepting_leads'])
            self.assertEqual([json.loads(request.content)['chat_id'] for request in self.telegram_requests], ['42', '43'])

    def test_logout_cancels_only_revoked_recipient_and_preserves_successful_ids(self) -> None:
        request_id = str(uuid4())
        with TestClient(self.app()) as client:
            store = client.app.state.store
            store.add_admin('42')
            store.add_admin('43')
            store.accept(request_id, '+420774411158', admin_chats=store.admin_chats())
            store.remove_admin('43')
            self.assertTrue(self.dispatch(client))
            self.assertEqual(store.get(request_id)['state'], 'cancelled')
            self.assertEqual(store.delivered_chats(request_id), ['42'])
            self.assertEqual({row['chat_id']: row['state'] for row in store.delivery_rows(request_id)},
                             {'42': 'sent', '43': 'cancelled'})
            self.assertEqual([json.loads(request.content)['chat_id'] for request in self.telegram_requests], ['42'])
            self.assertEqual(store.unresolved(), [])
            store.add_admin('43')
            self.assertFalse(self.dispatch(client))

    def test_failed_inflight_send_after_logout_does_not_requeue_after_reauth(self) -> None:
        request_id = str(uuid4())
        with TestClient(self.app()) as client:
            store = client.app.state.store
            store.add_admin('42')
            store.accept(request_id, '+420774411158', admin_chats=store.admin_chats())

            async def logout_during_send(row, chat_id):
                store.remove_admin(chat_id)
                store.add_admin(chat_id)
                return 'pending', 300, 'connection_unavailable'

            with patch.object(client.app.state.dispatcher.sender, 'send_one', side_effect=logout_during_send):
                self.assertTrue(self.dispatch(client))
            self.assertEqual(store.delivery_rows(request_id)[0]['state'], 'cancelled')
            self.assertEqual(store.get(request_id)['state'], 'cancelled')
            self.assertEqual(store.delivered_chats(request_id), [])
            self.assertFalse(self.dispatch(client))

    def test_successful_inflight_send_after_logout_records_actual_delivery(self) -> None:
        request_id = str(uuid4())
        with TestClient(self.app()) as client:
            store = client.app.state.store
            store.add_admin('42')
            store.accept(request_id, '+420774411158', admin_chats=store.admin_chats())

            async def logout_during_send(row, chat_id):
                store.remove_admin(chat_id)
                return 'sent', 0, ''

            with patch.object(client.app.state.dispatcher.sender, 'send_one', side_effect=logout_during_send):
                self.assertTrue(self.dispatch(client))
            self.assertFalse(store.is_admin('42'))
            self.assertEqual(store.delivery_rows(request_id)[0]['state'], 'sent')
            self.assertEqual(store.get(request_id)['state'], 'sent')
            self.assertEqual(store.delivered_chats(request_id), ['42'])
            self.assertFalse(self.dispatch(client))

    def test_telegram_rate_limit_is_retained_for_future_delivery(self) -> None:
        self.transport = httpx.MockTransport(
            lambda request: httpx.Response(
                429, json={"ok": False, "error_code": 429, "parameters": {"retry_after": 120}}
            )
        )
        payload = self.payload()
        with TestClient(self.app()) as client:
            self.assertEqual(self.post(client, payload).status_code, 202)
            before = time.time()
            self.assertTrue(self.dispatch(client))
            stored = client.app.state.store.get(payload["request_id"])
            self.assertEqual(stored["state"], "pending")
            self.assertGreaterEqual(stored["next_attempt"], before + 300)
            self.assertFalse(self.dispatch(client))
        with TestClient(self.app()) as client:
            self.assertEqual(client.app.state.store.get(payload["request_id"])["state"], "pending")

    def test_malformed_telegram_rate_limit_parameters_do_not_crash_dispatcher(self) -> None:
        for parameters in (None, [], "unexpected", {"retry_after": "soon"}):
            with self.subTest(parameters=parameters):
                self.transport = httpx.MockTransport(
                    lambda request: httpx.Response(
                        429, json={"ok": False, "error_code": 429, "parameters": parameters}
                    )
                )
                payload = self.payload()
                with TestClient(self.app()) as client:
                    self.assertEqual(self.post(client, payload).status_code, 202)
                    before = time.time()
                    self.assertTrue(self.dispatch(client))
                    stored = client.app.state.store.get(payload["request_id"])
                    self.assertEqual(stored["state"], "pending")
                    self.assertGreaterEqual(stored["next_attempt"], before + 300)

    def test_unusable_telegram_responses_are_not_reported_as_delivered(self) -> None:
        responses = (
            httpx.Response(200, json=[]),
            httpx.Response(200, json={"ok": True, "result": {}}),
            httpx.Response(200, json={"ok": True, "result": {"message_id": True}}),
            httpx.Response(200, content=b"<html>Bad Gateway</html>"),
            httpx.Response(503, json={"ok": False}),
        )
        for response in responses:
            with self.subTest(body=response.content):
                self.transport = httpx.MockTransport(lambda request: response)
                payload = self.payload()
                with TestClient(self.app()) as client:
                    self.assertEqual(self.post(client, payload).status_code, 202)
                    self.assertTrue(self.dispatch(client))
                    self.assertEqual(client.app.state.store.get(payload["request_id"])["state"], "pending")

    def test_invalid_telegram_chat_is_preserved_for_operator_action(self) -> None:
        self.transport = httpx.MockTransport(
            lambda request: httpx.Response(400, json={"ok": False, "error_code": 400, "description": "chat not found"})
        )
        payload = self.payload()
        with TestClient(self.app()) as client:
            self.assertEqual(self.post(client, payload).status_code, 202)
            self.assertTrue(self.dispatch(client))
            stored = client.app.state.store.get(payload["request_id"])
            self.assertEqual(stored["state"], "pending")
            self.assertFalse(self.dispatch(client))
        with TestClient(self.app()) as client:
            self.assertEqual(client.app.state.store.get(payload["request_id"])["state"], "pending")

    def test_logs_do_not_expose_token_phone_or_telegram_response(self) -> None:
        secret_description = "telegram-response-private-content"
        self.transport = httpx.MockTransport(
            lambda request: httpx.Response(400, json={"ok": False, "error_code": 400, "description": secret_description})
        )
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        logger = logging.getLogger()
        logger.addHandler(handler)
        previous_level = logger.level
        logger.setLevel(logging.INFO)
        try:
            with TestClient(self.app()) as client:
                self.assertEqual(self.post(client).status_code, 202)
                self.assertTrue(self.dispatch(client))
        finally:
            logger.setLevel(previous_level)
            logger.removeHandler(handler)
        self.assertIn("pending", output.getvalue())
        self.assertNotIn("test-token", output.getvalue())
        self.assertNotIn("+420774411158", output.getvalue())
        self.assertNotIn(secret_description, output.getvalue())

    def test_each_admin_delivery_is_retried_without_duplicate_success(self) -> None:
        delivered_chats: list[str] = []
        failed_once: set[str] = set()

        def partial_delivery(request: httpx.Request) -> httpx.Response:
            chat_id = json.loads(request.content)['chat_id']
            delivered_chats.append(chat_id)
            if chat_id in {'four', 'five'} and chat_id not in failed_once:
                failed_once.add(chat_id)
                raise httpx.ConnectTimeout('Temporary failure', request=request)
            return httpx.Response(200, json={'ok': True, 'result': {'message_id': len(delivered_chats)}})

        self.transport = httpx.MockTransport(partial_delivery)
        payload = self.payload()
        with TestClient(self.app()) as client:
            store = client.app.state.store
            store.add_admin('one', 'one')
            store.add_admin('two', 'two')
            store.add_admin('three', 'three')
            store.add_admin('four', 'four')
            store.add_admin('five', 'five')
            self.assertEqual(client.post('/leads', json=payload, headers=self.headers()).status_code, 202)
            self.assertTrue(client.portal.call(client.app.state.dispatcher.dispatch_once))
            self.assertEqual(delivered_chats, ['five', 'four', 'one', 'three', 'two'])
            self.assertEqual(store.get(payload['request_id'])['state'], 'pending')
            self.assertEqual(
                {row['chat_id']: row['state'] for row in store.delivery_rows(payload['request_id'])},
                {'one': 'sent', 'two': 'sent', 'three': 'sent', 'four': 'pending', 'five': 'pending'},
            )
            with store.db:
                store.db.execute(
                    'UPDATE leads SET next_attempt=0 WHERE request_id=?', (payload['request_id'],)
                )
                store.db.execute(
                    'UPDATE lead_deliveries SET next_attempt=0 WHERE request_id=? AND state=?',
                    (payload['request_id'], 'pending'),
                )
            self.assertTrue(client.portal.call(client.app.state.dispatcher.dispatch_once))
            self.assertEqual(delivered_chats, ['five', 'four', 'one', 'three', 'two', 'five', 'four'])
            self.assertEqual(store.get(payload['request_id'])['state'], 'sent')


class OutboxTests(BackendTestCase):
    def test_cancelled_leads_release_capacity_and_expire_after_retention(self) -> None:
        store = Store(self.database_path)
        old_time = time.time() - 8 * 86400
        try:
            store.add_admin('42')
            for index in range(1000):
                store.accept(f'old-{index}', '+420774411158', now=old_time, admin_chats=store.admin_chats())
            with patch('backend.storage.time.time', return_value=old_time):
                store.remove_admin('42')
            self.assertEqual(store.unresolved(), [])
            self.assertEqual(store.get('old-0')['state'], 'cancelled')
            self.assertEqual(store.delivered_chats('old-0'), [])
            store.accept('new', '+420774411159')
            store.cleanup(7)
            self.assertIsNone(store.get('old-0'))
            self.assertEqual(store.delivery_rows('old-0'), [])
            self.assertEqual(store.get('new')['state'], 'pending')
        finally:
            store.close()

    def test_crash_during_send_is_requeued_after_five_minutes(self) -> None:
        request_id = str(uuid4())
        store = Store(self.database_path)
        try:
            store.accept(request_id, "+420774411158")
            self.assertIsNotNone(store.claim())
            self.assertEqual(store.get(request_id)["state"], "sending")
        finally:
            store.close()
        store = Store(self.database_path)
        try:
            self.assertEqual(store.get(request_id)["state"], "pending")
            self.assertGreaterEqual(store.get(request_id)["next_attempt"], time.time() + 299)
            self.assertIsNone(store.claim())
            self.assertEqual([row["request_id"] for row in store.unresolved()], [request_id])
        finally:
            store.close()

    def test_retention_removes_old_delivered_leads_and_preserves_unresolved_leads(self) -> None:
        old_time = time.time() - 8 * 86400
        sent, pending, unknown = (str(uuid4()) for _ in range(3))
        store = Store(self.database_path)
        try:
            for request_id in (sent, pending, unknown):
                store.accept(request_id, "+420774411158", now=old_time)
            with patch("backend.storage.time.time", return_value=old_time):
                store.finish(sent, "sent")
                store.finish(unknown, "unknown")
            store.cleanup(7)
            self.assertIsNone(store.get(sent))
            self.assertEqual(store.get(pending)["state"], "pending")
            self.assertEqual(store.get(unknown)["state"], "unknown")
        finally:
            store.close()

    def test_outbox_capacity_preserves_existing_leads_instead_of_growing_forever(self) -> None:
        store = Store(self.database_path)
        first_id = str(uuid4())
        try:
            store.accept(first_id, "+420774411158")
            for _ in range(999):
                store.accept(str(uuid4()), "+420774411158")
            with self.assertRaises(Capacity):
                store.accept(str(uuid4()), "+420774411158")
            self.assertEqual(len(store.unresolved()), 1000)
            self.assertEqual(store.get(first_id)["phone"], "+420774411158")
            self.assertEqual(store.accept(first_id, "+420774411158"), "existing")
        finally:
            store.close()


class OperatorTests(BackendTestCase):
    def test_pending_command_omits_cancelled_leads(self) -> None:
        store = Store(self.database_path)
        try:
            store.add_admin('42')
            store.accept('cancelled', '+420774411158', admin_chats=store.admin_chats())
            store.remove_admin('42')
            store.accept('pending', '+420774411159')
            output = io.StringIO()
            with patch.dict(os.environ, {'DATABASE_PATH': self.database_path}, clear=True):
                with patch('sys.argv', ['backend.cli', 'pending']), redirect_stdout(output):
                    cli_main()
            self.assertEqual(json.loads(output.getvalue())['request_id'], 'pending')
        finally:
            store.close()

    def chats(self, response: httpx.Response) -> str:
        def reply(request: httpx.Request) -> httpx.Response:
            self.telegram_requests.append(request)
            return response

        client = httpx.Client(transport=httpx.MockTransport(reply))
        output = io.StringIO()
        with patch("backend.cli.httpx.Client", return_value=client), redirect_stdout(output):
            telegram_chats(Settings(telegram_token="test-token"))
        return output.getvalue()

    def test_chat_discovery_reads_updates_without_sending_or_acknowledging_them(self) -> None:
        group = {"id": -100123456, "type": "supergroup", "title": "ART PROJECT"}
        private = {"id": 123456, "type": "private", "first_name": "Owner"}
        output = self.chats(httpx.Response(200, json={
            "ok": True,
            "result": [
                {"update_id": 1, "message": {"chat": private}},
                {"update_id": 2, "my_chat_member": {"chat": group}},
                {"update_id": 3, "message": {"chat": group}},
            ],
        }))
        self.assertEqual(json.loads(output), [
            {"id": 123456, "type": "private", "name": "Owner"},
            {"id": -100123456, "type": "supergroup", "name": "ART PROJECT"},
        ])
        self.assertEqual(len(self.telegram_requests), 1)
        request = self.telegram_requests[0]
        self.assertEqual(request.method, "GET")
        self.assertTrue(request.url.path.endswith("/getUpdates"))
        self.assertEqual(request.url.params.get("timeout"), "0")
        self.assertNotIn("offset", request.url.params)

    def test_malformed_updates_are_rejected_with_a_safe_error(self) -> None:
        for result in (None, {}, [None], ["unexpected"], [{"message": None}], [{"message": {"chat": []}}]):
            with self.subTest(result=result):
                with self.assertRaises(ValueError) as raised:
                    self.chats(httpx.Response(200, json={"ok": True, "result": result}))
                self.assertNotIn("test-token", str(raised.exception))

    def test_pending_command_does_not_modify_or_send_leads(self) -> None:
        request_id = str(uuid4())
        store = Store(self.database_path)
        try:
            store.accept(request_id, "+420774411158")
            store.claim()
            output = io.StringIO()
            with patch.dict(os.environ, {"DATABASE_PATH": self.database_path}, clear=True):
                with patch("sys.argv", ["backend.cli", "pending"]), redirect_stdout(output):
                    with patch("backend.cli.httpx.Client", side_effect=AssertionError("No Telegram access expected")):
                        cli_main()
            item = json.loads(output.getvalue())
            self.assertEqual(item["request_id"], request_id)
            self.assertEqual(item["phone"], "+420774411158")
            self.assertEqual(item["state"], "sending")
            self.assertEqual(store.get(request_id)["state"], "sending")
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
