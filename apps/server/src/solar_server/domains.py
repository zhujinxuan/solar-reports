"""Domain schema endpoint for solar-server.

GET /api/schema — return DomainSchema list from solar-v2.

Compute (/api/domains/compute) and Excel export (/api/download/domains.xlsx)
serialize straight from ``ModelResults`` in ``solar_server._engine_serialize``;
no dag, no workbook on the serving path.
"""

from __future__ import annotations

import logging

from solar_v2.schema import DomainSchema

from solar_server.schemas import (
    DomainSchemaResponse,
    DomainsSchemaResponse,
    ItemSchemaResponse,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema loading — per-module defensive import
# ---------------------------------------------------------------------------

_DOMAIN_MODULES: tuple[str, ...] = (
    "solar_v2.domains.params",
    "solar_v2.domains.invest",
    "solar_v2.domains.debt",
    "solar_v2.domains.cost",
    "solar_v2.domains.pnl",
    "solar_v2.domains.cashflow",
    "solar_v2.domains.finplan",
    "solar_v2.domains.balance",
    "solar_v2.domains.valuation",
)


def _load_all_domains() -> list[DomainSchema]:
    """Import each domain module and collect SCHEMA where available.

    Modules without SCHEMA are skipped without blocking others, so partial
    schema coverage is tolerated.
    """
    raw: list[DomainSchema] = []
    for mod_name in _DOMAIN_MODULES:
        try:
            mod = __import__(mod_name, fromlist=["SCHEMA"])
            schema = getattr(mod, "SCHEMA", None)
            if isinstance(schema, DomainSchema):
                raw.append(schema)
        except Exception:
            logger.debug(
                "Failed to load schema from %s", mod_name, exc_info=True
            )
    return raw


def _convert_domain_schema(ds: DomainSchema) -> DomainSchemaResponse:
    """Convert a solar_v2 DomainSchema to the response model."""
    items: list[ItemSchemaResponse] = []
    for it in ds.items:
        items.append(
            ItemSchemaResponse(
                key=it.key,
                label=it.label,
                unit=it.unit,
                formula=it.formula,
                inputs=it.inputs,
                rows=it.rows,
            )
        )
    return DomainSchemaResponse(
        key=ds.key,
        sheet=ds.sheet,
        label=ds.label,
        depends_on=ds.depends_on,
        items=tuple(items),
    )


def _build_schema_response() -> DomainsSchemaResponse:
    """Build the schema response from solar-v2 domain schemas."""
    raw = _load_all_domains()
    domains = tuple(_convert_domain_schema(ds) for ds in raw)
    return DomainsSchemaResponse(domains=domains)
