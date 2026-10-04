from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar, final, overload

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
    DataObjectModel,
)
from projectkoios.references.io_limits import (
    RECONCILIATION_IO_LIMITS,
    ReferenceIOLimitError,
    ReferenceIOLimits,
    bounded_csv_field_size,
    bounded_utf8_size,
    validate_json_text_nesting,
)
from projectkoios.references.path_safety import (
    AuthorizedRoot,
    CloudPlaceholderProbe,
    PathLimitError,
    PathSafetyError,
    PlaceholderObservation,
    PlaceholderPreflightError,
    PlaceholderStatus,
    RootPreflightEvidence,
    RootStorageClass,
    authorize_root_preflight,
    read_path_bytes,
    validate_citekey,
)
from projectkoios.references.reconciliation_package import ContentEvidence

from ._contract import (
    _COLLECTION_ROWS_PARSER_VERSION,
    _limit_error,
    _required_limit,
    _stable_id,
    _validate_json_depth,
)
from .errors import CollectionReconciliationError

_Value = TypeVar("_Value")


@final
@dataclass(frozen=True)
class EvidenceMapping(DataObjectModel, Mapping[str, _Value]):
    """Immutable parsed values retaining exact input-byte evidence."""

    entries: tuple[tuple[str, _Value], ...]
    input_evidence: tuple[ContentEvidence, ...]
    root_preflights: tuple[RootPreflightEvidence, ...] = ()

    def __post_init__(self) -> None:
        keys = tuple(key for key, _ in self.entries)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("evidence mapping keys must be sorted and unique")

    def __getitem__(self, key: str) -> _Value:
        for candidate, value in self.entries:
            if candidate == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self.entries)

    def __len__(self) -> int:
        return len(self.entries)


@final
@dataclass(frozen=True)
class CollectionRowEvidence(DataObjectModel):
    source_bibliographies: tuple[str, ...]
    bibliographic_status: str
    reading_status: str
    observation_id: str | None = None
    source_content_id: str | None = None
    row_index: int | None = None
    parser_name: str | None = None
    parser_version: str | None = None

    def __post_init__(self) -> None:
        provenance = (
            self.observation_id,
            self.source_content_id,
            self.row_index,
            self.parser_name,
            self.parser_version,
        )
        if all(item is None for item in provenance):
            return
        if any(item is None for item in provenance):
            raise ValueError(
                "collection row provenance must be complete or absent"
            )
        if (
            re.fullmatch(
                r"collection-row-observation:sha256:[0-9a-f]{64}",
                str(self.observation_id),
            )
            is None
        ):
            raise ValueError("collection row observation identity is invalid")
        if (
            re.fullmatch(
                r"blob:sha256:[0-9a-f]{64}",
                str(self.source_content_id),
            )
            is None
        ):
            raise ValueError("collection row source identity is invalid")
        if type(self.row_index) is not int or self.row_index < 0:
            raise ValueError("collection row index is invalid")
        if not self.parser_name or not self.parser_version:
            raise ValueError("collection row parser identity is invalid")
        expected = _stable_id(
            "collection-row-observation",
            {
                "source_content_id": self.source_content_id,
                "row_index": self.row_index,
                "parser_name": self.parser_name,
                "parser_version": self.parser_version,
                "source_bibliographies": self.source_bibliographies,
                "bibliographic_status": self.bibliographic_status,
                "reading_status": self.reading_status,
            },
        )
        if self.observation_id != expected:
            raise ValueError("collection row observation identity differs")


@final
@dataclass(frozen=True)
class ManagedPdf(DataObjectModel):
    filename: str
    citekey: str
    sha256: str
    byte_size: int
    historically_verified: bool
    discovery_evidence: tuple[str, ...]


@final
@dataclass(frozen=True)
class ManagedPdfScan(DataObjectModel, Sequence[ManagedPdf]):
    pdfs: tuple[ManagedPdf, ...]
    input_evidence: tuple[ContentEvidence, ...]
    root_preflight: RootPreflightEvidence
    file_observations: tuple[PlaceholderObservation, ...]

    def __post_init__(self) -> None:
        if self.file_observations:
            raise ValueError(
                "complete managed-PDF scans cannot contain skipped "
                "file observations"
            )

    @overload
    def __getitem__(self, index: int) -> ManagedPdf: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[ManagedPdf, ...]: ...

    def __getitem__(
        self, index: int | slice
    ) -> ManagedPdf | tuple[ManagedPdf, ...]:
        return self.pdfs[index]

    def __len__(self) -> int:
        return len(self.pdfs)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionRowsLoadRequest(DataObjectActionRequest):
    path: Path
    storage_class: RootStorageClass
    placeholder_probe: CloudPlaceholderProbe | None = None
    limits: ReferenceIOLimits = RECONCILIATION_IO_LIMITS


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionRowsLoadResult(DataObjectActionResult):
    request: CollectionRowsLoadRequest
    rows: EvidenceMapping[CollectionRowEvidence]


@final
class CollectionRowsLoader(
    DataObjectActionizer[CollectionRowsLoadRequest, CollectionRowsLoadResult]
):
    def action(
        self, *, request: CollectionRowsLoadRequest
    ) -> CollectionRowsLoadResult:
        if type(request) is not CollectionRowsLoadRequest:
            raise TypeError("request must be a CollectionRowsLoadRequest")
        path = request.path
        storage_class = request.storage_class
        placeholder_probe = request.placeholder_probe
        limits = request.limits
        root_preflight = authorize_root_preflight(
            root_alias="collection-rows",
            storage_class=storage_class,
            placeholder_probe=placeholder_probe,
        )
        max_csv_bytes = _required_limit(limits.max_csv_bytes, "max_csv_bytes")
        try:
            content = read_path_bytes(
                path,
                label="collection rows",
                root_alias="collection-rows",
                storage_class=storage_class,
                placeholder_probe=placeholder_probe,
                max_bytes=max_csv_bytes,
            )
        except PathLimitError as error:
            raise _limit_error(error, limits) from error
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise CollectionReconciliationError(
                "collection rows are not UTF-8"
            ) from error
        max_rows = _required_limit(limits.max_rows, "max_rows")
        max_text_bytes = _required_limit(
            limits.max_text_bytes, "max_text_bytes"
        )
        result: dict[str, CollectionRowEvidence] = {}
        source_content_id = "blob:sha256:" + hashlib.sha256(content).hexdigest()
        try:
            with bounded_csv_field_size(max_text_bytes):
                rows = csv.DictReader(io.StringIO(text, newline=""))
                for row_number, row in enumerate(rows, start=1):
                    if row_number > max_rows:
                        raise ReferenceIOLimitError(
                            resource="collection rows",
                            limit_name="max_rows",
                            limit=max_rows,
                            observed=row_number,
                            limits=limits,
                        )
                    for field_name, field_value in row.items():
                        if field_value is None:
                            continue
                        field_bytes = bounded_utf8_size(
                            field_value, max_bytes=max_text_bytes
                        )
                        if field_bytes > max_text_bytes:
                            raise ReferenceIOLimitError(
                                resource=(
                                    f"collection row {row_number} field "
                                    f"{field_name}"
                                ),
                                limit_name="max_text_bytes",
                                limit=max_text_bytes,
                                observed=field_bytes,
                                limits=limits,
                            )
                    citekey = (row.get("citekey") or "").strip()
                    if not citekey:
                        raise CollectionReconciliationError(
                            "collection row has an empty citekey"
                        )
                    try:
                        validate_citekey(citekey)
                    except PathSafetyError as error:
                        raise CollectionReconciliationError(
                            f"collection row has an unsafe citekey: {citekey}"
                        ) from error
                    if citekey in result:
                        raise CollectionReconciliationError(
                            f"duplicate collection row: {citekey}"
                        )
                    sources = tuple(
                        item
                        for item in (
                            row.get("source_bibliographies") or ""
                        ).split(";")
                        if item
                    )
                    max_sources = _required_limit(
                        limits.max_candidates, "max_candidates"
                    )
                    if len(sources) > max_sources:
                        raise ReferenceIOLimitError(
                            resource=f"collection row {row_number} source list",
                            limit_name="max_candidates",
                            limit=max_sources,
                            observed=len(sources),
                            limits=limits,
                        )
                    bibliographic_status = (
                        row.get("bibliographic_status") or "unrecorded"
                    )
                    reading_status = row.get("reading_status") or "unrecorded"
                    row_payload = {
                        "source_content_id": source_content_id,
                        "row_index": row_number - 1,
                        "parser_name": "projectkoios-collection-csv",
                        "parser_version": _COLLECTION_ROWS_PARSER_VERSION,
                        "source_bibliographies": sources,
                        "bibliographic_status": bibliographic_status,
                        "reading_status": reading_status,
                    }
                    result[citekey] = CollectionRowEvidence(
                        source_bibliographies=sources,
                        bibliographic_status=bibliographic_status,
                        reading_status=reading_status,
                        observation_id=_stable_id(
                            "collection-row-observation", row_payload
                        ),
                        source_content_id=source_content_id,
                        row_index=row_number - 1,
                        parser_name="projectkoios-collection-csv",
                        parser_version=_COLLECTION_ROWS_PARSER_VERSION,
                    )
        except csv.Error as error:
            if "field larger than field limit" in str(error):
                raise ReferenceIOLimitError(
                    resource="collection rows CSV field",
                    limit_name="max_text_bytes",
                    limit=max_text_bytes,
                    observed=max_text_bytes + 1,
                    limits=limits,
                ) from error
            raise CollectionReconciliationError(
                "collection rows CSV is malformed"
            ) from error
        return CollectionRowsLoadResult(
            request=request,
            rows=EvidenceMapping(
                entries=tuple(sorted(result.items())),
                input_evidence=(
                    ContentEvidence.from_bytes(
                        role="collection-rows",
                        filename="inputs/collection-rows.csv",
                        content=content,
                    ),
                ),
                root_preflights=(root_preflight,),
            ),
        )


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ManagedPdfScanRequest(DataObjectActionRequest):
    directory: Path
    storage_class: RootStorageClass
    placeholder_probe: CloudPlaceholderProbe | None = None
    source_discovery: Path | None = None
    source_discovery_storage_class: RootStorageClass | None = None
    limits: ReferenceIOLimits = RECONCILIATION_IO_LIMITS


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ManagedPdfScanResult(DataObjectActionResult):
    request: ManagedPdfScanRequest
    scan: ManagedPdfScan


@final
class ManagedPdfScanner(
    DataObjectActionizer[ManagedPdfScanRequest, ManagedPdfScanResult]
):
    def action(self, *, request: ManagedPdfScanRequest) -> ManagedPdfScanResult:
        if type(request) is not ManagedPdfScanRequest:
            raise TypeError("request must be a ManagedPdfScanRequest")
        directory = request.directory
        storage_class = request.storage_class
        placeholder_probe = request.placeholder_probe
        source_discovery = request.source_discovery
        source_discovery_storage_class = request.source_discovery_storage_class
        limits = request.limits
        try:
            root = AuthorizedRoot.existing(
                directory,
                label="managed PDF root",
                root_alias="managed-pdfs",
                storage_class=storage_class,
                placeholder_probe=placeholder_probe,
            )
            relative_files = root.iter_files(
                suffix=".pdf",
                recursive=False,
                max_files=_required_limit(limits.max_files, "max_files"),
                max_entries=_required_limit(limits.max_entries, "max_entries"),
                max_depth=1,
            )
        except PathLimitError as error:
            raise _limit_error(error, limits) from error
        except PlaceholderPreflightError:
            raise
        except PathSafetyError as error:
            raise CollectionReconciliationError(str(error)) from error
        if (source_discovery is None) != (
            source_discovery_storage_class is None
        ):
            raise ValueError(
                "source discovery path and storage class must be supplied "
                "together"
            )
        historical: dict[str, tuple[str, tuple[str, ...]]]
        discovery_evidence: tuple[ContentEvidence, ...]
        if source_discovery is None:
            historical, discovery_evidence = ({}, ())
        else:
            assert source_discovery_storage_class is not None
            historical, discovery_evidence = _load_source_discovery(
                source_discovery,
                storage_class=source_discovery_storage_class,
                placeholder_probe=placeholder_probe,
                limits=limits,
            )
        pdfs: list[ManagedPdf] = []
        file_observations: list[PlaceholderObservation] = []
        asset_evidence: list[ContentEvidence] = []
        total_bytes = 0
        max_file_bytes = _required_limit(
            limits.max_file_bytes, "max_file_bytes"
        )
        max_total_bytes = _required_limit(
            limits.max_total_bytes, "max_total_bytes"
        )
        for relative in relative_files:
            try:
                citekey = validate_citekey(Path(relative.name).stem)
                preflight = root.preflight_file(relative)
                if preflight.status is not PlaceholderStatus.ORDINARY_FILE:
                    raise PlaceholderPreflightError(preflight)
                observation = root.observe_file(
                    relative, max_bytes=max_file_bytes, prefix_bytes=5
                )
            except PathLimitError as error:
                raise _limit_error(error, limits) from error
            except PlaceholderPreflightError:
                raise
            except PathSafetyError as error:
                raise CollectionReconciliationError(str(error)) from error
            byte_size = observation.byte_size
            if byte_size <= 0:
                raise CollectionReconciliationError(
                    f"managed PDF size is outside bounds: {relative.name}"
                )
            if observation.prefix != b"%PDF-":
                raise CollectionReconciliationError(
                    f"managed file lacks PDF header: {relative.name}"
                )
            total_bytes += byte_size
            if total_bytes > max_total_bytes:
                raise ReferenceIOLimitError(
                    resource="managed PDFs",
                    limit_name="max_total_bytes",
                    limit=max_total_bytes,
                    observed=total_bytes,
                    limits=limits,
                )
            digest = observation.sha256
            asset_evidence.append(
                ContentEvidence(
                    role="managed-asset",
                    filename=f"inputs/managed-assets/{relative.name}",
                    byte_size=byte_size,
                    sha256=digest,
                )
            )
            discovery = historical.get(citekey)
            if discovery is not None and discovery[0] == digest:
                verified = True
                evidence = discovery[1]
            else:
                verified = False
                evidence = ()
            pdfs.append(
                ManagedPdf(
                    filename=relative.name,
                    citekey=citekey,
                    sha256=digest,
                    byte_size=byte_size,
                    historically_verified=verified,
                    discovery_evidence=evidence,
                )
            )
        return ManagedPdfScanResult(
            request=request,
            scan=ManagedPdfScan(
                pdfs=tuple(pdfs),
                input_evidence=tuple(
                    sorted(
                        (*discovery_evidence, *asset_evidence),
                        key=lambda value: (
                            value.role,
                            value.filename,
                            value.byte_size,
                            value.sha256,
                        ),
                    )
                ),
                root_preflight=root.preflight_evidence,
                file_observations=tuple(
                    sorted(
                        file_observations,
                        key=lambda item: item.relative_path or "",
                    )
                ),
            ),
        )


def _load_source_discovery(
    path: Path | None,
    *,
    storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
    limits: ReferenceIOLimits = RECONCILIATION_IO_LIMITS,
) -> tuple[dict[str, tuple[str, tuple[str, ...]]], tuple[ContentEvidence, ...]]:
    if path is None:
        return ({}, ())
    try:
        content = read_path_bytes(
            path,
            label="source-discovery document",
            root_alias="source-discovery",
            storage_class=storage_class,
            placeholder_probe=placeholder_probe,
            max_bytes=_required_limit(limits.max_json_bytes, "max_json_bytes"),
        )
    except PathLimitError as error:
        raise _limit_error(error, limits) from error
    try:
        text = content.decode("utf-8")
        validate_json_text_nesting(
            text, limits=limits, resource="source discovery JSON"
        )
        data = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CollectionReconciliationError(
            "source-discovery document is invalid"
        ) from error
    _validate_json_depth(data, limits=limits, resource="source discovery")
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise CollectionReconciliationError(
            "unsupported source-discovery document"
        )
    matches = data.get("matches")
    if not isinstance(matches, list):
        raise CollectionReconciliationError(
            "source-discovery matches are invalid"
        )
    max_records = _required_limit(limits.max_candidates, "max_candidates")
    if len(matches) > max_records:
        raise ReferenceIOLimitError(
            resource="source-discovery matches",
            limit_name="max_candidates",
            limit=max_records,
            observed=len(matches),
            limits=limits,
        )
    result: dict[str, tuple[str, tuple[str, ...]]] = {}
    for item in matches:
        if not isinstance(item, dict):
            raise CollectionReconciliationError(
                "source-discovery match must be an object"
            )
        citekey = item.get("citekey")
        digest = item.get("sha256")
        basis = item.get("match_basis")
        if (
            not isinstance(citekey, str)
            or not citekey
            or (not isinstance(digest, str))
            or (re.fullmatch("[0-9a-f]{64}", digest) is None)
            or (not isinstance(basis, str))
            or (not basis)
        ):
            raise CollectionReconciliationError(
                "source-discovery match identity is incomplete"
            )
        maximum_text = _required_limit(limits.max_text_bytes, "max_text_bytes")
        basis_bytes = bounded_utf8_size(basis, max_bytes=maximum_text)
        if basis_bytes > maximum_text:
            raise ReferenceIOLimitError(
                resource="source-discovery match basis",
                limit_name="max_text_bytes",
                limit=maximum_text,
                observed=basis_bytes,
                limits=limits,
            )
        try:
            validate_citekey(citekey, field="source-discovery citekey")
        except PathSafetyError as error:
            raise CollectionReconciliationError(str(error)) from error
        if citekey in result:
            raise CollectionReconciliationError(
                f"duplicate source-discovery citekey: {citekey}"
            )
        result[citekey] = (digest, (basis,))
    return (
        result,
        (
            ContentEvidence.from_bytes(
                role="source-discovery",
                filename="inputs/source-discovery.json",
                content=content,
            ),
        ),
    )
