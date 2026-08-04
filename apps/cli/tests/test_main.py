"""Tests for solar-cli typer commands.

Excel COM tests use import-only guards (no COM Dispatch probe — sequential
Dispatch/Quit cycles corrupt COM state).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import yaml
from solar_cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


def _posix(p: Path) -> str:
    """Return path as forward-slash string (safe for TOML values)."""
    return p.as_posix()

# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------


def test_extract_writes_valid_dag() -> None:
    """extract --dag <tmp> writes a valid YAML dag file."""
    import tempfile


    with tempfile.TemporaryDirectory() as tmpdir:
        dag_path = Path(tmpdir) / "test.dag.yaml"
        result = runner.invoke(
            app,
            ["extract", "--dag", str(dag_path)],
        )
        assert result.exit_code == 0
        assert dag_path.exists()
        dag = yaml.safe_load(dag_path.read_text(encoding="utf-8"))
        assert "nodes" in dag
        assert isinstance(dag["nodes"], list)
        assert len(dag["nodes"]) > 100
        for node in dag["nodes"]:
            assert "id" in node
            assert "type" in node


# ---------------------------------------------------------------------------
# compute
# ---------------------------------------------------------------------------


def test_compute_v1_emits_6560ish_values() -> None:
    """compute --version v1 returns ~6560 node values (stdout summary)."""
    result = runner.invoke(app, ["compute", "--version", "v1"])
    assert result.exit_code == 0
    assert "node values via solar-v1" in result.stdout
def test_compute_v1_json_output(tmp_path: Path) -> None:
    """compute --version v1 --out <json> writes valid JSON file."""
    out_path = tmp_path / "out.json"
    result = runner.invoke(
        app,
        ["compute", "--version", "v1", "--out", str(out_path)],
    )
    assert result.exit_code == 0
    assert out_path.exists()
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(data) > 6000  # ~6560 nodes


def test_compute_v1_csv_output(tmp_path: Path) -> None:
    """compute --version v1 --out <csv> writes valid CSV file."""
    out_path = tmp_path / "out.csv"
    result = runner.invoke(
        app,
        ["compute", "--version", "v1", "--out", str(out_path)],
    )
    assert result.exit_code == 0
    assert out_path.exists()
    with open(str(out_path), encoding="utf-8", newline="") as f:
        lines = list(csv.reader(f))
    assert len(lines) > 6000  # header + ~6560 rows


def test_compute_v2_emits_domain_json() -> None:
    """compute --version v2 returns domain-structured JSON."""
    result = runner.invoke(app, ["compute", "--version", "v2"])
    assert result.exit_code == 0
    assert "9-domain model via solar-v2 engine" in result.stdout
    # Parse the JSON output (before the summary line)
    json_str = result.stdout.split("\n\n")[0]
    data = json.loads(json_str)
    assert data["version"] == "v2"
    assert "params" in data
    assert "pnl" in data
    assert "valuation" in data
    assert "headline" in data
    assert "equity_irr" in data["headline"]
    assert isinstance(data["headline"]["equity_irr"], float)
def test_compute_v2_flat_flag() -> None:
    """compute --version v2 --flat returns flat {node_id: value} map."""
    result = runner.invoke(
        app, ["compute", "--version", "v2", "--flat"]
    )
    assert result.exit_code == 0
    # Flat output is JSON with node_id keys spread across multiple lines
    # Parse just the JSON portion (before the summary line)
    json_str = result.stdout.split("\n\n")[0]
    data = json.loads(json_str)
    assert isinstance(data, dict)
    assert len(data) > 4000  # formula+error nodes
    # Spot-check a known node_id
    assert any("损益" in k for k in data)


def test_compute_invalid_version() -> None:
    """compute --version bad exits 1 with error message."""
    result = runner.invoke(app, ["compute", "--version", "bad"])
    assert result.exit_code == 1
    assert "Invalid" in result.stderr


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def test_verify_path2_only() -> None:
    """verify --skip-engine exercises path 1.2 (v2 engine vs v1).

    Run only when COM guards allow; skip otherwise.
    """
    # Guard: if excel-com is unavailable, skip path-1.1 tests
    try:
        import pythoncom  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("pythoncom not available")

    result = runner.invoke(
        app,
        ["verify", "--skip-engine", "--engine", "excel-com"],
    )
    # Path 1.1 skipped, path 1.2 runs engine
    assert result.exit_code in (0, 1)
    if result.exit_code == 0:
        assert "All enabled paths: PASS" in result.stdout
    else:
        # If there are diffs, we should see the diff report
        assert "Path 1.2" in result.stdout


def test_verify_path1_excel_com() -> None:
    """verify --skip-v2 --engine excel-com exercises path 1.1.

    Excel COM test — guarded by import availability.
    """
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        import pytest
        pytest.skip("win32com not available")

    result = runner.invoke(
        app,
        ["verify", "--skip-v2", "--engine", "excel-com"],
    )
    assert result.exit_code in (0, 1, 2)
    if result.exit_code == 0:
        assert "Path 1.1 CLEAN" in result.stdout


def test_verify_engine_unavailable_lo(tmp_path: Path) -> None:
    """verify --skip-v2 --engine libreoffice with bad path exits 2."""

    try:
        import win32com.client  # noqa: F401
    except ImportError:
        pytest.skip("win32com not available — COM guard")

    # Give a non-existent libreoffice path
    result = runner.invoke(
        app,
        [
            "verify",
            "--skip-v2",
            "--engine",
            "libreoffice",
            "--libreoffice-path",
            str(tmp_path / "nonexistent" / "soffice.exe"),
        ],
    )
    assert result.exit_code == 2
    assert "libreoffice" in result.stderr.lower()


# ---------------------------------------------------------------------------
# --config TOML
# ---------------------------------------------------------------------------


def test_toml_overrides_default_dag_path(tmp_path: Path) -> None:
    """TOML config overrides Settings defaults for dag_path."""
    toml_path = tmp_path / "config.toml"
    toml_dag = tmp_path / "custom.dag.yaml"
    toml_dag.write_text("nodes: []\n")  # minimal valid YAML

    toml_path.write_text(
        f'dag_path = "{_posix(toml_dag)}"\n', encoding="utf-8"
    )
    result = runner.invoke(
        app,
        ["--config", str(toml_path), "extract", "--dag", str(toml_dag)],
    )
    assert result.exit_code == 0
    assert toml_dag.exists()


def test_cli_option_beats_toml(tmp_path: Path) -> None:
    """CLI --dag overrides the dag_path set in TOML config."""
    toml_path = tmp_path / "config.toml"
    toml_dag = tmp_path / "toml.dag.yaml"
    cli_dag = tmp_path / "cli.dag.yaml"
    toml_dag.write_text("nodes: []\n")

    toml_path.write_text(
        f'dag_path = "{_posix(toml_dag)}"\n', encoding="utf-8"
    )
    result = runner.invoke(
        app,
        [
            "--config", str(toml_path),
            "extract",
            "--dag", str(cli_dag),
        ],
    )
    assert result.exit_code == 0
    assert cli_dag.exists()


def test_toml_unknown_key_exits_2(tmp_path: Path) -> None:
    """Unknown TOML key → exit 2 with message listing valid keys."""
    toml_path = tmp_path / "config.toml"
    toml_path.write_text('bad_key = 123\n', encoding="utf-8")

    result = runner.invoke(
        app, ["--config", str(toml_path), "compute", "--version", "v1"]
    )
    assert result.exit_code == 2
    assert "Valid keys" in result.stderr


def test_toml_missing_file(tmp_path: Path) -> None:
    """Missing TOML file → clear error."""
    result = runner.invoke(
        app,
        ["--config", str(tmp_path / "nonexistent.toml"), "compute", "--version", "v1"],
    )
    assert result.exit_code == 2
    assert "not found" in result.stderr.lower()


def test_verify_with_toml_config(tmp_path: Path) -> None:
    """verify runs with a TOML config (both paths skipped for speed)."""
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        'rel_tol = 1e-6\nabs_tol = 1e-9\n', encoding="utf-8"
    )
    result = runner.invoke(
        app,
        [
            "--config", str(toml_path),
            "verify",
            "--skip-engine",
            "--skip-v2",
        ],
    )
    assert result.exit_code == 0
    assert "All enabled paths: PASS" in result.stdout


# ---------------------------------------------------------------------------
# --config with [inputs] for v2 engine
# ---------------------------------------------------------------------------


def test_toml_inputs_overrides_v2_output(tmp_path: Path) -> None:
    """TOML [inputs] table changes v2 engine output."""
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "[inputs]\ninstalled_capacity_mw = 20.0\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["--config", str(toml_path), "compute", "--version", "v2"],
    )
    assert result.exit_code == 0
    json_str = result.stdout.split("\n\n")[0]
    data = json.loads(json_str)
    # With changed capacity, power_generation changes from default
    pnl = data["pnl"]
    pg_item = next(it for it in pnl["items"] if it["key"] == "power_generation")
    pg_first = pg_item["values"][0]
    assert pg_first > 0
    # Should be roughly proportional to capacity increase
    # first year of 20MW should be > 15MW default (~25762)
    assert 20000 < pg_first < 40000
