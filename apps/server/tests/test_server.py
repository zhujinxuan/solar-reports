"""Tests for solar-server FastAPI app — fastapi.testclient.TestClient.

Engine-backed verify tests call verify() directly to avoid COM apartment
threading conflicts between FastAPI's threadpool and the async test client.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from solar_server.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


def test_health() -> None:
    """GET /health returns ok with version list."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["versions"] == ["v1", "v2"]


# ---------------------------------------------------------------------------
# POST /compute/v1
# ---------------------------------------------------------------------------


def test_compute_v1_node_count() -> None:
    """POST /compute/v1 returns 6560 nodes (all nodes in DAG)."""
    response = client.post("/compute/v1")
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == "v1"
    assert data["node_count"] == 6560


def test_compute_v1_spot_values() -> None:
    """Spot-check known values from the DAG cached values."""
    response = client.post("/compute/v1")
    data = response.json()
    values = data["values"]

    # Literal value
    assert values["参数表!C2"] == 15
    # Float with tolerance handled by JSON serialization
    pnl = values["损益!H8"]
    assert isinstance(pnl, (int, float))
    assert abs(pnl - 5910.444690265486) < 1e-6


def test_compute_v1_error_node() -> None:
    """Error nodes should be serialized as {"error": "#REF!"}."""
    response = client.post("/compute/v1")
    data = response.json()
    values = data["values"]

    ref_err = values.get("损益!D4")
    assert isinstance(ref_err, dict)
    assert ref_err.get("error") == "#REF!"


def test_compute_v1_filter() -> None:
    """POST /compute/v1 with node_ids filter returns only those nodes."""
    response = client.post(
        "/compute/v1",
        json={"node_ids": ["参数表!C2", "损益!H8"]},
    )
    data = response.json()
    assert data["node_count"] == 2
    assert set(data["values"].keys()) == {"参数表!C2", "损益!H8"}


def test_compute_v1_cache_reuse() -> None:
    """Two calls to /compute/v1 should be fast (cache hit)."""
    r1 = client.post("/compute/v1")
    assert r1.status_code == 200
    r2 = client.post("/compute/v1")
    assert r2.status_code == 200
    assert r1.json()["node_count"] == r2.json()["node_count"]


# ---------------------------------------------------------------------------
# POST /compute/v2
# ---------------------------------------------------------------------------


def test_compute_v2_node_count() -> None:
    """POST /compute/v2 returns 6560 nodes."""
    response = client.post("/compute/v2")
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == "v2"
    assert data["node_count"] == 6560


def test_compute_v2_spot_values() -> None:
    """Spot-check known values from v2 compute."""
    response = client.post("/compute/v2")
    data = response.json()
    values = data["values"]

    assert values["参数表!C2"] == 15
    cf = values["现金流量!G22"]
    assert isinstance(cf, (int, float))
    assert abs(cf - 5887.319431208464) < 1e-6


def test_compute_v2_filter() -> None:
    """POST /compute/v2 with node_ids filter."""
    response = client.post(
        "/compute/v2",
        json={"node_ids": ["参数表!C2", "参数表!C36"]},
    )
    data = response.json()
    assert data["node_count"] == 2
    assert data["values"]["参数表!C36"] == 0.13


# ---------------------------------------------------------------------------
# POST /compute/v3 → 422
# ---------------------------------------------------------------------------


def test_compute_v3_422() -> None:
    """POST /compute/v3 returns 422 (unknown version)."""
    response = client.post("/compute/v3")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "v3" in detail


# ---------------------------------------------------------------------------
# POST /verify (non-engine paths via HTTP, engine paths direct)
# ---------------------------------------------------------------------------


def test_verify_skip_engine() -> None:
    """POST /verify with skip_engine=true → path_1_2 ok."""
    response = client.post("/verify", json={"skip_engine": True})
    assert response.status_code == 200
    data = response.json()

    assert data["path_1_1"]["skipped"] is True
    assert data["path_1_2"]["ok"] is True
    assert data["path_1_2"]["mismatch_count"] == 0
    # v2 may return a subset of all 6560 nodes (its contract is to cover
    # formula+error nodes), so total should be >= 5059.
    assert data["path_1_2"]["total"] >= 5059
    assert data["ok"] is True


def test_verify_engine_unavailable_503() -> None:
    """POST /verify with engine='nonexistent' → 503."""
    response = client.post("/verify", json={"engine": "nonexistent"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "nonexistent" in detail


# ---------------------------------------------------------------------------
# Engine-backed verify — direct calls to avoid COM + async event loop crash
# ---------------------------------------------------------------------------


def test_verify_path_1_1_excel_com() -> None:
    """Path 1.1: excel-com recalc vs v1 → 0 mismatches (direct call)."""
    from solar_server.verify import _run_path_1_1
    from xlsx_core.settings import Settings

    settings = Settings()
    result = _run_path_1_1(settings, "excel-com")

    # Not a Path11Skipped when we explicitly call the internal function
    from solar_server.schemas import Path11Skipped

    assert not isinstance(result, Path11Skipped)
    assert result.ok is True
    assert result.mismatch_count == 0
    assert result.total == 5059
    assert result.engine == "excel-com"


def test_verify_path_1_2() -> None:
    """Path 1.2: v1 vs v2 → 0 mismatches (direct call)."""
    from solar_server.verify import _run_path_1_2
    from xlsx_core.settings import Settings

    settings = Settings()
    result = _run_path_1_2(settings)
    assert result.ok is True
    assert result.mismatch_count == 0
    assert result.total >= 5059



def test_verify_skip_v2_http() -> None:
    """POST /verify with skip_v2=true, skip_engine=true via HTTP."""
    response = client.post(
        "/verify",
        json={"skip_v2": True, "skip_engine": True},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["path_1_1"]["skipped"] is True
    assert data["path_1_2"] is None
    assert data["ok"] is True
