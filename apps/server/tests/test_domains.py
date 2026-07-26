"""Tests for domain schema/compute/download endpoints."""
from __future__ import annotations

import io

import openpyxl
from fastapi.testclient import TestClient
from solar_server.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/schema
# ---------------------------------------------------------------------------


def test_api_schema_returns_domains() -> None:
    """GET /api/schema returns domain list with items."""
    r = client.get("/api/schema")
    assert r.status_code == 200
    data = r.json()
    assert "domains" in data
    domains = data["domains"]
    # At minimum, pnl with 35 items is available; SchemaSlice may add more.
    assert len(domains) >= 1
    # Check one domain has expected structure
    pnl = next((d for d in domains if d["key"] == "pnl"), None)
    assert pnl is not None, "pnl domain must be present"
    assert pnl["sheet"] == "损益"
    assert len(pnl["items"]) == 35
    # Spot-check first item structure
    sales = next((i for i in pnl["items"] if i["key"] == "sales_revenue"), None)
    assert sales is not None
    assert sales["label"] == "销售收入"
    assert sales["unit"] == "万元"
    assert "power_generation" in sales["formula"]


# ---------------------------------------------------------------------------
# POST /api/domains/compute
# ---------------------------------------------------------------------------


def test_domains_compute_v2_returns_cells() -> None:
    """POST /api/domains/compute v2 returns cells with values."""
    r = client.post("/api/domains/compute", json={"version": "v2"})
    assert r.status_code == 200
    data = r.json()
    assert data["version"] == "v2"
    domains = data["domains"]
    assert len(domains) >= 1

    pnl = next((d for d in domains if d["key"] == "pnl"), None)
    assert pnl is not None
    assert pnl["sheet"] == "损益"

    # Spot-check sales_revenue item has cells
    sales = next((i for i in pnl["items"] if i["key"] == "sales_revenue"), None)
    assert sales is not None
    assert len(sales["cells"]) > 0

    # Spot-check 损益!G8 value matches dag cached oracle (5645.35030420354)
    g8 = next((c for c in sales["cells"] if c["node"] == "损益!G8"), None)
    assert g8 is not None
    assert abs(float(g8["value"]) - 5645.35030420354) < 1e-6


def test_domains_compute_v1_works() -> None:
    """POST /api/domains/compute v1 also works."""
    r = client.post("/api/domains/compute", json={"version": "v1"})
    assert r.status_code == 200
    data = r.json()
    assert data["version"] == "v1"
    assert len(data["domains"]) >= 1


def test_domains_compute_v3_422() -> None:
    """POST /api/domains/compute v3 returns 422."""
    r = client.post("/api/domains/compute", json={"version": "v3"})
    assert r.status_code == 422
    assert "v3" in r.json()["detail"]


def test_domains_compute_defaults_to_v2() -> None:
    """POST /api/domains/compute without body defaults to v2."""
    r = client.post("/api/domains/compute")
    assert r.status_code == 200
    assert r.json()["version"] == "v2"


# ---------------------------------------------------------------------------
# GET /api/download/domains.xlsx
# ---------------------------------------------------------------------------


def test_download_xlsx_returns_valid_file() -> None:
    """GET /api/download/domains.xlsx returns valid xlsx with expected sheets."""
    r = client.get("/api/download/domains.xlsx", params={"version": "v2"})
    assert r.status_code == 200
    assert r.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "domains.xlsx" in r.headers["content-disposition"]

    # Parse the xlsx bytes
    buf = io.BytesIO(r.content)
    wb = openpyxl.load_workbook(buf)

    # Should have domain sheets (at least pnl=损益)
    sheet_names = wb.sheetnames
    assert "损益" in sheet_names

    # Check the 损益 sheet has expected headers
    ws = wb["损益"]
    # Row 1: header — 项目 | 公式 | 单位 | ...
    header_row = [cell.value for cell in ws[1]]
    assert header_row[0] == "项目"
    assert header_row[1] == "公式"
    assert header_row[2] == "单位"

    # Has data rows
    max_row = ws.max_row
    assert max_row > 1, "Expected data rows beyond header"

    # Spot-check: find 销售收入 row
    found_sales = False
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, values_only=True):
        if row[0] == "销售收入":
            found_sales = True
            # Formula column should have the formula text
            assert row[1] is not None
            break
    assert found_sales, "Should find 销售收入 row"

    wb.close()


def test_download_xlsx_v1_works() -> None:
    """GET /api/download/domains.xlsx v1 returns 200."""
    r = client.get("/api/download/domains.xlsx", params={"version": "v1"})
    assert r.status_code == 200


def test_download_xlsx_v3_422() -> None:
    """GET /api/download/domains.xlsx v3 returns 422."""
    r = client.get("/api/download/domains.xlsx", params={"version": "v3"})
    assert r.status_code == 422
    assert "v3" in r.json()["detail"]


def test_download_xlsx_freezes_header() -> None:
    """XLSX sheet has frozen top row."""
    r = client.get("/api/download/domains.xlsx", params={"version": "v2"})
    assert r.status_code == 200
    buf = io.BytesIO(r.content)
    wb = openpyxl.load_workbook(buf)
    ws = wb["损益"]
    assert ws.freeze_panes == "A2"
    wb.close()


# ---------------------------------------------------------------------------
# Static mount — gracefully handled if dir missing
# ---------------------------------------------------------------------------


def test_root_serves_or_falls_through() -> None:
    """GET / returns something (static or fallback — not a crash)."""
    # In test, the static dir may not exist yet (FrontendSlice writes it).
    # The server mounts it only if the dir exists; otherwise the root path
    # would 404 because no route is registered for /.
    r = client.get("/")
    # Either 200 (static served) or 404 (no static dir mounted, no route for /)
    assert r.status_code in (200, 404)
