"""Tests for solar-server FastAPI app — fastapi.testclient.TestClient.

Excel COM tests use import-only guards. Engine-backed verify tests call
verify functions directly to avoid COM + async event loop issues.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from solar_server.main import app
from solar_server.schemas import Path11Result

client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


def test_health() -> None:
    """GET /health returns ok with version list."""
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["versions"] == ["v1", "v2"]


# ---------------------------------------------------------------------------
# POST /compute/v1
# ---------------------------------------------------------------------------


def test_compute_v1_node_count() -> None:
    """POST /compute/v1 returns 6560 nodes (all nodes in DAG)."""
    r = client.post("/compute/v1")
    assert r.status_code == 200
    data = r.json()
    assert data["node_count"] == 6560


def test_compute_v1_spot_values() -> None:
    """Spot-check known values from the DAG cached values."""
    r = client.post("/compute/v1")
    assert r.status_code == 200
    data = r.json()
    values = data["values"]
    # 损益!G8 = 5645.35030420354
    pnl = values.get("损益!G8")
    assert pnl is not None
    assert abs(pnl - 5645.35030420354) < 1e-6


def test_compute_v1_error_node() -> None:
    """Error nodes should be serialized as {"error": "#REF!"}."""
    r = client.post("/compute/v1")
    assert r.status_code == 200
    data = r.json()
    values = data["values"]
    # Find an error node — any node whose value is an error marker
    ref_err = None
    for _k, v in values.items():
        if isinstance(v, dict) and "error" in v:
            ref_err = v
            break
    assert ref_err is not None
    assert ref_err.get("error") == "#REF!"


def test_compute_v1_filter() -> None:
    """POST /compute/v1 with node_ids filter returns only those nodes."""
    r = client.post(
        "/compute/v1",
        json={"node_ids": ["参数表!C2", "损益!H8"]},
    )
    assert r.status_code == 200
    data = r.json()
    assert set(data["values"].keys()) == {"参数表!C2", "损益!H8"}


def test_compute_v1_cache_reuse() -> None:
    """Two calls to /compute/v1 should both succeed (cache hit)."""
    r1 = client.post("/compute/v1")
    r2 = client.post("/compute/v1")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["node_count"] == r2.json()["node_count"]


# ---------------------------------------------------------------------------
# POST /compute/v2
# ---------------------------------------------------------------------------


def test_compute_v2_returns_domain_json() -> None:
    """POST /compute/v2 returns domain-structured JSON."""
    r = client.post("/compute/v2")
    assert r.status_code == 200
    data = r.json()
    values = data["values"]
    assert values["version"] == "v2"
    assert "params" in values
    assert "pnl" in values
    assert "valuation" in values
    assert "headline" in values
    assert isinstance(values["headline"]["equity_irr"], float)


def test_compute_v2_flat_flag() -> None:
    """POST /compute/v2 with flat=true returns node_id map."""
    r = client.post("/compute/v2", json={"flat": True})
    assert r.status_code == 200
    data = r.json()
    values = data["values"]
    # Should be flat {node_id: value}
    assert isinstance(values, dict)
    assert len(values) > 4000
    assert any("损益" in k for k in values)


def test_compute_v2_inputs_override() -> None:
    """POST /compute/v2 with inputs override changes output."""
    r_default = client.post("/compute/v2")
    assert r_default.status_code == 200
    default_data = r_default.json()

    r_override = client.post(
        "/compute/v2",
        json={"inputs": {"installed_capacity_mw": 5.0}},
    )
    assert r_override.status_code == 200
    override_data = r_override.json()

    # With 5MW vs 15MW default, power_generation first value should differ
    default_pg = default_data["values"]["pnl"]["items"][1]
    override_pg = override_data["values"]["pnl"]["items"][1]
    assert default_pg["key"] == "power_generation"
    assert override_pg["key"] == "power_generation"
    # 5MW / 15MW = 1/3 the default
    ratio = override_pg["values"][0] / default_pg["values"][0]
    assert abs(ratio - 5.0 / 15.0) < 0.01


# ---------------------------------------------------------------------------
# POST /compute/v3 -> 422
# ---------------------------------------------------------------------------


def test_compute_v3_422() -> None:
    """POST /compute/v3 returns 422 (unknown version)."""
    r = client.post("/compute/v3")
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "v3" in detail


# ---------------------------------------------------------------------------
# POST /verify (non-engine paths via HTTP, engine paths direct)
# ---------------------------------------------------------------------------


def test_verify_skip_engine() -> None:
    """POST /verify with skip_engine=true -> path_1_2 runs."""
    r = client.post("/verify", json={"skip_engine": True, "skip_v2": True})
    assert r.status_code == 200
    data = r.json()
    # Both skipped -> ok should be true
    assert data["ok"] is True


def test_verify_engine_unavailable_503() -> None:
    """POST /verify with engine='nonexistent' -> 503."""
    r = client.post("/verify", json={"engine": "nonexistent"})
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "nonexistent" in detail


# ---------------------------------------------------------------------------
# Engine-backed verify — direct calls to avoid COM + async event loop crash
# ---------------------------------------------------------------------------


def test_verify_path_1_1_excel_com() -> None:
    """Path 1.1: excel-com recalc vs v1 -> 0 mismatches (direct call)."""
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("win32com not available")

    from solar_server.verify import _run_path_1_1
    from xlsx_core.settings import Settings

    s = Settings()
    result = _run_path_1_1(s, "excel-com")
    assert isinstance(result, Path11Result)
    assert result.ok
    assert result.mismatch_count == 0
    assert result.engine == "excel-com"


def test_verify_path_1_2() -> None:
    """Path 1.2: v2 engine vs v1 -> 0 mismatches (direct call)."""
    from solar_server.verify import _run_path_1_2
    from xlsx_core.settings import Settings

    s = Settings()
    result = _run_path_1_2(s)
    assert result.ok
    assert result.mismatch_count == 0
    assert result.total >= 5059


def test_verify_skip_v2_http() -> None:
    """POST /verify with skip_v2=true, skip_engine=true via HTTP."""
    r = client.post("/verify", json={"skip_v2": True, "skip_engine": True})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
