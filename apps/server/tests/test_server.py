"""Tests for solar-server FastAPI app — fastapi.testclient.TestClient.

Serving is v2-only: the golden check (v1 vs workbook, v2 vs v1) lives in
packages/solar-v1 tests, solar-v2 tests, and the CLI (`solar-cli verify`).
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from solar_server.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


def test_health() -> None:
    """GET /health returns ok; serving reports v2 only."""
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["versions"] == ["v2"]


# ---------------------------------------------------------------------------
# Removed v1/verify surface — serving carries no dag interpreter
# ---------------------------------------------------------------------------


def test_compute_v1_route_removed() -> None:
    """POST /compute/v1 is gone — the server has no dag interpreter.

    Removed paths fall through to the GET-only StaticFiles mount, so the
    response is 405 (Method Not Allowed), not 404.
    """
    r = client.post("/compute/v1")
    assert r.status_code == 405


def test_verify_route_removed() -> None:
    """POST /verify is gone — golden check lives in CLI and package tests."""
    r = client.post("/verify", json={"skip_engine": True, "skip_v2": True})
    assert r.status_code == 405


# ---------------------------------------------------------------------------
# URL prefix mount (SOLAR_URL_PREFIX / create_app(url_prefix=...))
# ---------------------------------------------------------------------------


def test_url_prefix_mount() -> None:
    """create_app(url_prefix=...) serves app + static under the prefix only."""
    from solar_server.main import create_app

    prefixed = TestClient(create_app(url_prefix="/solar-server"))
    r = prefixed.get("/solar-server/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    # static frontend reachable under the prefix
    page = prefixed.get("/solar-server/")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    # root is no longer served
    assert prefixed.get("/health").status_code == 404


def test_url_prefix_env(monkeypatch) -> None:
    """SOLAR_URL_PREFIX env var applies when url_prefix is not passed."""
    from solar_server.main import create_app

    monkeypatch.setenv("SOLAR_URL_PREFIX", "/solar-server")
    prefixed = TestClient(create_app())
    assert prefixed.get("/solar-server/health").status_code == 200
    assert prefixed.get("/health").status_code == 404
