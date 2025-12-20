#!/usr/bin/env python3
"""
FastAPI in-process tests for Trust API using TestClient (no external server required).
"""

import os

import pytest
from fastapi.testclient import TestClient

from trust_api.main import app


@pytest.fixture(scope="module")
def client():
    os.environ["STANZA_SKIP_INIT"] = "1"
    with TestClient(app) as c:
        yield c


def test_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert "version" in data
    assert data.get("docs") == "/docs"


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}
