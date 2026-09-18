from __future__ import annotations

import csv
import hashlib
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Final


@dataclass(frozen=True)
class ReferenceIOLimits:
    """Effective hard limits for one reference-I/O operation.

    ``None`` means that a dimension does not apply to the operation.  It never
    means "unbounded": callers must select a profile that bounds every input
    dimension they consume.
    """

    profile: str
    max_files: int | None = None
    max_file_bytes: int | None = None
    max_response_bytes: int | None = None
    max_cache_bytes: int | None = None
    max_total_bytes: int | None = None
    max_rows: int | None = None
    max_json_bytes: int | None = None
    max_csv_bytes: int | None = None
    max_bibliography_bytes: int | None = None
    max_json_depth: int | None = None
    max_nesting_depth: int | None = None
    max_text_bytes: int | None = None
    max_text_file_bytes: int | None = None
    max_text_total_bytes: int | None = None
    max_candidates: int | None = None
    max_match_evaluations: int | None = None
    max_entries: int | None = None

    def __post_init__(self) -> None:
        if (
            not self.profile
            or len(self.profile) > 128
            or len(self.profile.encode("utf-8")) > 128
        ):
            raise ValueError("I/O-limit profile must be non-empty and bounded")
        hard_ceilings = {
            "max_files": 100_000,
            "max_file_bytes": 4_000_000_000,
            "max_response_bytes": 2_000_000,
            "max_cache_bytes": 3_000_000,
            "max_total_bytes": 40_000_000_000,
            "max_rows": 100_000,
            "max_json_bytes": 20_000_000,
            "max_csv_bytes": 50_000_000,
            "max_bibliography_bytes": 50_000_000,
            "max_json_depth": 64,
            "max_nesting_depth": 128,
            "max_text_bytes": 1_000_000,
            "max_text_file_bytes": 50_000_000,
            "max_text_total_bytes": 100_000_000,
            "max_candidates": 100_000,
            "max_match_evaluations": 1_000_000,
            "max_entries": 100_000,
        }
        for name, value in asdict(self).items():
            if name == "profile" or value is None:
                continue
            ceiling = hard_ceilings[name]
            if type(value) is not int or not 0 < value <= ceiling:
                raise ValueError(
                    f"{name} must be a positive integer no greater than "
                    f"{ceiling}, or null"
                )

    def to_dict(self) -> dict[str, str | int | None]:
        return asdict(self)

    @property
    def evidence_id(self) -> str:
        encoded = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        return (
            "reference-io-limits:sha256:" + hashlib.sha256(encoded).hexdigest()
        )


_CSV_FIELD_LIMIT_LOCK = threading.Lock()


@contextmanager
def bounded_csv_field_size(maximum_characters: int) -> Iterator[None]:
    """Apply one process-global CSV field ceiling under a serialization lock."""
    if not 0 < maximum_characters <= 1_000_000:
        raise ValueError("CSV field limit is outside the hard ceiling")
    with _CSV_FIELD_LIMIT_LOCK:
        previous = csv.field_size_limit()
        csv.field_size_limit(maximum_characters)
        try:
            yield
        finally:
            csv.field_size_limit(previous)


class ReferenceIOLimitError(ValueError):
    """A typed, fail-closed diagnostic for incomplete bounded observation."""

    code = "reference-io-limit-exceeded"
    coverage_status = "incomplete"

    def __init__(
        self,
        *,
        resource: str,
        limit_name: str,
        limit: int,
        observed: int,
        limits: ReferenceIOLimits,
    ) -> None:
        self.resource = resource
        self.limit_name = limit_name
        self.limit = limit
        self.observed = observed
        self.limits = limits
        description = (
            "text byte limit"
            if limit_name
            in {
                "max_text_bytes",
                "max_text_file_bytes",
                "max_text_total_bytes",
            }
            else "byte limit"
            if "bytes" in limit_name
            else limit_name
        )
        super().__init__(
            f"{resource} exceeds {description} ({limit_name}): "
            f"observed {observed}, limit {limit}; coverage remains incomplete"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "coverage_status": self.coverage_status,
            "resource": self.resource,
            "limit_name": self.limit_name,
            "limit": self.limit,
            "observed": self.observed,
            "effective_limits": self.limits.to_dict(),
            "effective_limits_id": self.limits.evidence_id,
        }

    def to_json(self) -> str:
        """Render a deterministic incomplete-coverage status artifact."""
        return (
            json.dumps(
                self.to_dict(),
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )


BIBLIOGRAPHY_IO_LIMITS: Final = ReferenceIOLimits(
    profile="bibliography-v1",
    max_files=1,
    max_file_bytes=50_000_000,
    max_total_bytes=50_000_000,
    max_text_file_bytes=50_000_000,
    max_text_total_bytes=50_000_000,
    max_rows=10_000,
    max_bibliography_bytes=50_000_000,
    max_nesting_depth=128,
    max_text_bytes=1_000_000,
    max_candidates=10_000,
    max_entries=10_000,
)

ASSET_DISCOVERY_IO_LIMITS: Final = ReferenceIOLimits(
    profile="asset-discovery-v1",
    max_files=10_000,
    max_file_bytes=4_000_000_000,
    max_total_bytes=40_000_000_000,
    max_json_bytes=20_000_000,
    max_json_depth=64,
    max_text_bytes=4_096,
    max_candidates=100_000,
    max_match_evaluations=100_000,
    max_entries=20_000,
)

ACQUISITION_IO_LIMITS: Final = ReferenceIOLimits(
    profile="acquisition-v1",
    max_files=256,
    max_file_bytes=4_000_000_000,
    max_total_bytes=40_000_000_000,
    max_rows=256,
    max_json_bytes=1_000_000,
    max_csv_bytes=1_000_000,
    max_json_depth=64,
    max_nesting_depth=64,
    max_text_bytes=4_096,
    max_candidates=256,
    max_entries=1_024,
)

RECONCILIATION_PACKAGE_IO_LIMITS: Final = ReferenceIOLimits(
    profile="reconciliation-package-v1",
    max_files=100_000,
    max_file_bytes=50_000_000,
    max_total_bytes=100_000_000,
    max_json_bytes=20_000_000,
    max_json_depth=64,
    max_entries=100_000,
)
RECONCILIATION_IO_LIMITS: Final = ReferenceIOLimits(
    profile="collection-reconciliation-v1",
    max_files=10_000,
    max_file_bytes=4_000_000_000,
    max_total_bytes=40_000_000_000,
    max_text_file_bytes=50_000_000,
    max_text_total_bytes=50_000_000,
    max_rows=10_000,
    max_json_bytes=20_000_000,
    max_csv_bytes=50_000_000,
    max_bibliography_bytes=50_000_000,
    max_json_depth=64,
    max_nesting_depth=128,
    max_text_bytes=4_096,
    max_candidates=10_000,
    max_entries=20_000,
)

VALIDATION_IO_LIMITS: Final = ReferenceIOLimits(
    profile="reference-validation-v1",
    max_files=20_000,
    max_file_bytes=1_000_000,
    max_total_bytes=50_000_000,
    max_text_file_bytes=1_000_000,
    max_text_total_bytes=50_000_000,
    max_text_bytes=4_096,
    max_candidates=10_000,
    max_entries=40_000,
)

IDENTITY_IO_LIMITS: Final = ReferenceIOLimits(
    profile="identity-replay-v1",
    max_files=10_000,
    max_file_bytes=10_000_000,
    max_total_bytes=100_000_000,
    max_json_bytes=10_000_000,
    max_json_depth=64,
    max_nesting_depth=64,
    max_text_bytes=1_000_000,
    max_candidates=10_000,
    max_entries=10_000,
)

METADATA_IO_LIMITS: Final = ReferenceIOLimits(
    profile="metadata-provider-v1",
    max_files=1_000,
    max_file_bytes=3_000_000,
    max_response_bytes=2_000_000,
    max_cache_bytes=3_000_000,
    max_total_bytes=500_000_000,
    max_json_bytes=3_000_000,
    max_json_depth=64,
    max_nesting_depth=64,
    max_text_bytes=512_000,
    max_candidates=10_000,
    max_entries=2_000,
)


def bounded_utf8_size(value: str, *, max_bytes: int) -> int:
    """Count UTF-8 bytes with bounded temporary allocation and early stop."""
    if len(value) > max_bytes:
        return len(value)
    total = 0
    for offset in range(0, len(value), 65_536):
        total += len(value[offset : offset + 65_536].encode("utf-8"))
        if total > max_bytes:
            return total
    return total


def validate_json_text_nesting(
    text: str,
    *,
    limits: ReferenceIOLimits,
    resource: str,
) -> None:
    """Reject oversized or deeply nested JSON before parser allocation."""
    maximum_bytes = limits.max_json_bytes
    if maximum_bytes is None:
        raise ValueError("JSON I/O profile must define max_json_bytes")
    observed_bytes = bounded_utf8_size(text, max_bytes=maximum_bytes)
    if observed_bytes > maximum_bytes:
        raise ReferenceIOLimitError(
            resource=resource,
            limit_name="max_json_bytes",
            limit=maximum_bytes,
            observed=observed_bytes,
            limits=limits,
        )
    maximum_depth = limits.max_json_depth
    if maximum_depth is None:
        raise ValueError("JSON I/O profile must define max_json_depth")
    depth = 0
    quoted = False
    escaped = False
    for character in text:
        if escaped:
            escaped = False
            continue
        if quoted and character == "\\":
            escaped = True
            continue
        if character == '"':
            quoted = not quoted
            continue
        if quoted:
            continue
        if character in "[{":
            depth += 1
            if depth > maximum_depth:
                raise ReferenceIOLimitError(
                    resource=resource,
                    limit_name="max_json_depth",
                    limit=maximum_depth,
                    observed=depth,
                    limits=limits,
                )
        elif character in "]}":
            depth = max(0, depth - 1)
