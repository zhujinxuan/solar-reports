"""Fast YAML I/O with mtime-keyed caching.

yaml.safe_load on the 1.2MB dag costs ~16s pure-Python; CSafeLoader is ~6x
faster. Repeated loads of the same file in one process are served from a
modification-time-keyed cache (a compute run touches the doc 3+ times).
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict, TypeVar, cast

import yaml

try:  # libyaml-backed loaders are ~6-10x faster
    _Loader = yaml.CSafeLoader
    _Dumper = yaml.CSafeDumper
except AttributeError:  # pragma: no cover - libyaml missing
    _Loader = yaml.SafeLoader
    _Dumper = yaml.SafeDumper

T = TypeVar("T")

_cache: dict[tuple[str, float], object] = {}


def load_doc(path: str | Path) -> object:
    """Parse a YAML file, cached by (path, mtime)."""
    p = Path(path)
    key = (str(p.resolve()), p.stat().st_mtime)
    if key not in _cache:
        with open(p, encoding="utf-8") as f:
            _cache.clear()  # single-doc cache: stale entries never survive
            _cache[key] = yaml.load(f, Loader=_Loader)
    return _cache[key]


class DagNodeDoc(TypedDict, total=False):
    """One node entry in dag.yaml."""

    id: str
    sheet: str
    col: str
    row: int
    type: str
    expression: str | None
    value: object
    year_series: dict[str, object] | None


class DagDocument(TypedDict, total=False):
    """The dag.yaml top-level document."""

    version: int
    source: str
    defined_names: dict[str, str]
    nodes: list[DagNodeDoc]


def load_dag_doc(path: str | Path) -> DagDocument:
    """load_doc specialized to the dag schema of record."""
    return cast(DagDocument, load_doc(path))


def dump_doc(doc: object, path: str | Path) -> None:
    """Serialize to YAML (UTF-8, unicode, fast dumper), then re-cache."""
    p = Path(path)
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(doc, f, Dumper=_Dumper, allow_unicode=True, sort_keys=False)
    _cache.clear()
