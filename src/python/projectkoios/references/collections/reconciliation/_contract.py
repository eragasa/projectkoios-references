from __future__ import annotations

import hashlib

from projectkoios.references.io_limits import (
    ReferenceIOLimitError,
    ReferenceIOLimits,
)
from projectkoios.references.path_safety import (
    PathLimitError,
)
from projectkoios.references.reconciliation_package import (
    canonical_json_bytes,
)

_SCHEMA_VERSION = 5

_PROCESSOR_VERSION = "0.10.0"

_COLLECTION_ROWS_PARSER_VERSION = "1"

_SOURCE_DISCOVERY_PARSER_VERSION = "1"

_REFERENCE_EVIDENCE_CONSUMER_VERSION = "1"

_MAX_RECORDS = 10_000

_MAX_INPUT_JSON_BYTES = 10_000_000

_MAX_COLLECTION_ROWS_BYTES = 50_000_000

_MAX_TEX_FILES = 10_000

_MAX_TEX_BYTES = 50_000_000

_MAX_PDF_BYTES = 4_000_000_000

_EXPECTED_PDF_TYPES = frozenset(
    {
        "article",
        "book",
        "booklet",
        "conference",
        "inbook",
        "incollection",
        "inproceedings",
        "mastersthesis",
        "phdthesis",
        "proceedings",
        "techreport",
        "unpublished",
    }
)


def _required_limit(value: int | None, name: str) -> int:
    if value is None:
        raise ValueError(
            f"collection-reconciliation I/O profile must define {name}"
        )
    return value


def _limit_error(
    error: PathLimitError,
    limits: ReferenceIOLimits,
) -> ReferenceIOLimitError:
    return ReferenceIOLimitError(
        resource=error.resource,
        limit_name=error.limit_name,
        limit=error.limit,
        observed=error.observed,
        limits=limits,
    )


def _validate_json_depth(
    value: object,
    *,
    limits: ReferenceIOLimits,
    resource: str,
) -> None:
    max_depth = _required_limit(limits.max_json_depth, "max_json_depth")
    pending: list[tuple[object, int]] = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        if depth > max_depth:
            raise ReferenceIOLimitError(
                resource=resource,
                limit_name="max_json_depth",
                limit=max_depth,
                observed=depth,
                limits=limits,
            )
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)


def _stable_id(kind: str, payload: object) -> str:
    canonical = canonical_json_bytes(payload)
    return f"{kind}:sha256:{hashlib.sha256(canonical).hexdigest()}"
