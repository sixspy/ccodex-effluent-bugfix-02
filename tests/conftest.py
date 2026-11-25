"""BF02 日切修复测试公共夹具（临时库，夹具按 fixtures/ 播种）。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import app
from db import init_db


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "bf02.db")
    init_db()
    return TestClient(app)


def _login(c: TestClient, username: str, password: str) -> dict:
    r = c.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def admin_headers(client):
    return _login(client, "admin", "admin123")


@pytest.fixture
def writer_headers(client):
    return _login(client, "writer", "writer123")
