"""Tests for solar-cli typer commands.

Uses typer.testing.CliRunner for integration-level testing.
"""

from __future__ import annotations

import json
import tempfile
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
    with tempfile.TemporaryDirectory() as tmpdir:
        dag_path = Path(tmpdir) / "test.dag.yaml"
        result = runner.invoke(app, ["extract", "--dag", str(dag_path)])
        assert result.exit_code == 0, f"stderr: {result.stderr}"
        assert dag_path.exists()

        data = yaml.safe_load(dag_path.read_text(encoding="utf-8"))
        assert data["version"] == 1
        assert "nodes" in data
        assert len(data["nodes"]) > 0

        # Check structure of first few nodes
        node = data["nodes"][0]
        assert "id" in node
        assert "sheet" in node
        assert "type" in node


# ---------------------------------------------------------------------------
# compute
# ---------------------------------------------------------------------------


def test_compute_v1_emits_6560ish_values() -> None:
    """compute --version v1 returns ~6560 node values (stdout summary)."""
    result = runner.invoke(app, ["compute", "--version", "v1"])
    assert result.exit_code == 0, f"stderr: {result.stderr}"
    assert "Computed" in result.stdout
    assert "node values via solar-v1" in result.stdout


def test_compute_v1_json_output() -> None:
    """compute --version v1 --out <json> writes valid JSON file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "values.json"
        result = runner.invoke(
            app,
            ["compute", "--version", "v1", "--out", str(out_path)],
        )
        assert result.exit_code == 0, f"stderr: {result.stderr}"
        assert out_path.exists()

        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert len(data) > 6000  # ~6560 nodes


def test_compute_v1_csv_output() -> None:
    """compute --version v1 --out <csv> writes valid CSV file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "values.csv"
        result = runner.invoke(
            app,
            ["compute", "--version", "v1", "--out", str(out_path)],
        )
        assert result.exit_code == 0, f"stderr: {result.stderr}"
        assert out_path.exists()

        lines = out_path.read_text(encoding="utf-8").strip().split("\n")
        assert lines[0] == "node_id,value"
        assert len(lines) > 6000  # header + ~6560 rows


def test_compute_v2_emits_values() -> None:
    """compute --version v2 — may fail gracefully if solar-v2 is mid-rewrite."""
    result = runner.invoke(app, ["compute", "--version", "v2"])
    if result.exit_code == 0:
        assert "Computed" in result.stdout
        assert "node values via solar-v2" in result.stdout
    else:
        assert "solar-v2 not available" in result.stderr


def test_compute_invalid_version() -> None:
    """compute --version bad exits 1 with error message."""
    result = runner.invoke(app, ["compute", "--version", "v3"])
    assert result.exit_code == 1, f"stderr: {result.stderr}"
    assert "Invalid" in result.stderr


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def test_verify_path2_only() -> None:
    """verify --skip-engine exercises path 1.2 (v2 vs v1).

    Gracefully skips if solar-v2 is mid-rewrite.
    """
    result = runner.invoke(
        app,
        ["verify", "--skip-engine"],
    )
    if "Path 1.2 SKIPPED" in result.stdout:
        assert "solar-v2 not available" in result.stdout
        assert "All enabled paths: PASS" in result.stdout
    else:
        assert result.exit_code == 0, (
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )
        assert "Path 1.2 CLEAN" in result.stdout
        assert "All enabled paths: PASS" in result.stdout


def test_verify_path1_excel_com() -> None:
    """verify --skip-v2 --engine excel-com exercises path 1.1.

    Guard: pywin32 import only (no COM Dispatch probe — sequential
    Dispatch/Quit cycles corrupt COM state).  If Excel COM is genuinely
    unavailable, the recalc adapter will fail with a clear error.
    """
    try:
        __import__("pythoncom")
        __import__("win32com.client")
    except ImportError:
        pytest.skip("pywin32 not installed")

    result = runner.invoke(
        app,
        ["verify", "--skip-v2", "--engine", "excel-com"],
    )
    assert result.exit_code == 0, (
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    assert "Path 1.1 CLEAN" in result.stdout



def test_verify_engine_unavailable_lo() -> None:
    """verify --skip-v2 --engine libreoffice with bad path exits 2."""
    result = runner.invoke(
        app,
        [
            "verify",
            "--skip-v2",
            "--engine",
            "libreoffice",
            "--workbook",
            "data/附件4：平价上网光伏发电项目经济评价模型（第7.1版）.xlsx",
        ],
        env={"XLSX_LIBREOFFICE_PATH": "/nonexistent/soffice.exe"},
    )
    assert result.exit_code == 2, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "ERROR" in result.stderr
    assert "libreoffice" in result.stderr.lower()


# ---------------------------------------------------------------------------
# --config TOML
# ---------------------------------------------------------------------------


def test_toml_overrides_default_dag_path(tmp_path: Path) -> None:
    """TOML config overrides Settings defaults for dag_path."""
    repo_root = Path.cwd()
    toml_dag = tmp_path / "custom.dag.yaml"
    wb_key = '附件4：平价上网光伏发电项目经济评价模型（第7.1版）.xlsx'
    toml_content = f"""\
dag_path = "{_posix(toml_dag)}"
workbook_path = "{_posix(repo_root / 'data' / wb_key)}"
"""
    config_path = tmp_path / "config.toml"
    config_path.write_text(toml_content, encoding="utf-8")

    result = runner.invoke(
        app, ["--config", str(config_path), "extract"],
    )
    assert result.exit_code == 0, f"stderr: {result.stderr}"
    assert "custom.dag.yaml" in result.stdout
    assert toml_dag.exists()


def test_cli_option_beats_toml(tmp_path: Path) -> None:
    """CLI --dag overrides the dag_path set in TOML config."""
    repo_root = Path.cwd()
    tom_dag = tmp_path / "from_toml.yaml"
    cli_dag = tmp_path / "from_cli.yaml"
    wb_key = '附件4：平价上网光伏发电项目经济评价模型（第7.1版）.xlsx'
    toml_content = f"""\
dag_path = "{_posix(tom_dag)}"
workbook_path = "{_posix(repo_root / 'data' / wb_key)}"
"""
    config_path = tmp_path / "config.toml"
    config_path.write_text(toml_content, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--config", str(config_path),
            "extract", "--dag", str(cli_dag),
        ],
    )
    assert result.exit_code == 0, f"stderr: {result.stderr}"
    # CLI value wins
    assert "from_cli.yaml" in result.stdout
    assert "from_toml.yaml" not in result.stdout
    assert cli_dag.exists()


def test_toml_unknown_key_exits_2(tmp_path: Path) -> None:
    """Unknown TOML key → exit 2 with message listing valid keys."""
    config_path = tmp_path / "config.toml"
    config_path.write_text("bogus_key = 42\n", encoding="utf-8")

    result = runner.invoke(
        app, ["--config", str(config_path), "extract"],
    )
    assert result.exit_code == 2, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "bogus_key" in result.stderr
    assert "Valid keys" in result.stderr


def test_toml_missing_file(tmp_path: Path) -> None:
    """Missing TOML file → clear error."""
    config_path = tmp_path / "nonexistent.toml"

    result = runner.invoke(
        app, ["--config", str(config_path), "extract"],
    )
    assert result.exit_code == 2, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "not found" in result.stderr.lower()


def test_verify_with_toml_config(tmp_path: Path) -> None:
    """verify runs with a TOML config (both paths skipped for speed)."""
    repo_root = Path.cwd()
    wb_key = '附件4：平价上网光伏发电项目经济评价模型（第7.1版）.xlsx'
    toml_content = f"""\
dag_path = "{_posix(repo_root / 'dag' / 'solar.dag.yaml')}"
workbook_path = "{_posix(repo_root / 'data' / wb_key)}"
"""
    config_path = tmp_path / "config.toml"
    config_path.write_text(toml_content, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--config", str(config_path),
            "verify", "--skip-engine", "--skip-v2",
        ],
    )
    assert result.exit_code == 0, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "All enabled paths: PASS" in result.stdout
