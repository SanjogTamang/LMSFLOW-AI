import os
import uuid
from collections import defaultdict

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role")
os.environ.setdefault("LMS_CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())

from backend.main import app


class InMemoryDatabase:
    def __init__(self):
        self.rows = defaultdict(list)

    def select(self, table, filters=None, columns="*", single=False, order_by=None, limit=None):
        rows = [dict(row) for row in self.rows[table] if all(row.get(k) == v for k, v in (filters or {}).items())]
        if order_by:
            rows.sort(key=lambda row: row.get(order_by) or "", reverse=True)
        if limit:
            rows = rows[:limit]
        return rows[0] if single and rows else (None if single else rows)

    def insert(self, table, values):
        row = dict(values)
        row.setdefault("id", str(uuid.uuid4()))
        row.setdefault("created_at", "2026-01-01T00:00:00+00:00")
        self.rows[table].append(row)
        return dict(row)

    def update(self, table, filters, values):
        changed = []
        for row in self.rows[table]:
            if all(row.get(k) == v for k, v in filters.items()):
                row.update(values)
                changed.append(dict(row))
        return changed

    def upsert(self, table, values):
        for row in self.rows[table]:
            if row.get("id") == values.get("id"):
                row.update(values)
                return dict(row)
        return self.insert(table, values)

    def delete(self, table, filters):
        removed = [row for row in self.rows[table] if all(row.get(k) == v for k, v in filters.items())]
        self.rows[table] = [row for row in self.rows[table] if not all(row.get(k) == v for k, v in filters.items())]
        return removed


class FakeAuth:
    def __init__(self):
        self.accounts = {}
        self.tokens = {}

    def sign_up(self, payload):
        email = payload["email"]
        if email in self.accounts:
            raise ValueError("already registered")
        user_id = str(uuid.uuid4())
        self.accounts[email] = {"id": user_id, "password": payload["password"], "metadata": payload["options"]["data"]}
        token = f"token-{user_id}"
        self.tokens[token] = user_id
        return type("R", (), {"user": type("U", (), {"id": user_id, "email": email, "user_metadata": payload["options"]["data"]})(),
                             "session": type("S", (), {"access_token": token})()})()

    def sign_in_with_password(self, payload):
        account = self.accounts.get(payload["email"])
        if not account or account["password"] != payload["password"]:
            raise ValueError("bad credentials")
        token = f"token-{account['id']}"
        self.tokens[token] = account["id"]
        return type("R", (), {"user": type("U", (), {"id": account["id"], "email": payload["email"], "user_metadata": account["metadata"]})(),
                             "session": type("S", (), {"access_token": token})()})()

    def get_user(self, token):
        user_id = self.tokens.get(token)
        if not user_id:
            raise ValueError("invalid token")
        email = next(email for email, account in self.accounts.items() if account["id"] == user_id)
        account = self.accounts[email]
        return type("R", (), {"user": type("U", (), {"id": user_id, "email": email, "user_metadata": account["metadata"]})()})()


class FakeSupabase:
    def __init__(self):
        self.auth = FakeAuth()


@pytest.fixture
def fake_db(monkeypatch):
    db = InMemoryDatabase()
    auth = FakeSupabase()
    monkeypatch.setattr("backend.database.get_database", lambda: db)
    monkeypatch.setattr("backend.database.get_supabase_client", lambda: auth)
    monkeypatch.setattr("backend.routers.auth_router.get_database", lambda: db)
    monkeypatch.setattr("backend.routers.auth_router.get_supabase_client", lambda: auth)
    monkeypatch.setattr("backend.routers.assignments_router.get_database", lambda: db)
    monkeypatch.setattr("backend.routers.drafts_router.get_database", lambda: db)
    monkeypatch.setattr("backend.routers.documents_router.get_database", lambda: db)
    monkeypatch.setattr("backend.routers.jobs_router.get_database", lambda: db)
    monkeypatch.setattr("backend.routers.lms_router.get_database", lambda: db)
    monkeypatch.setattr("backend.worker.get_database", lambda: db)
    return db


@pytest.fixture
def client(fake_db):
    return TestClient(app)


@pytest.fixture
def student_a():
    return {"student_id": "20240301001", "password": "Password123!", "full_name": "Student A", "email": "studentA@scu.ac.kr"}


@pytest.fixture
def student_b():
    return {"student_id": "20240301002", "password": "Password123!", "full_name": "Student B", "email": "studentB@scu.ac.kr"}
