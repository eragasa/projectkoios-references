from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import Path

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
    RootStorageClass,
    authorize_root_preflight,
    read_path_bytes,
    validate_citekey,
)
from projectkoios.references.reconciliation_package import (
    ContentEvidence,
)

from ._contract import (
    _COLLECTION_ROWS_PARSER_VERSION,
    _limit_error,
    _required_limit,
    _stable_id,
    _validate_json_depth,
)
from .evidence import _content_evidence_key
from .models import (
    CollectionReconciliationError,
    CollectionRowEvidence,
    EvidenceMapping,
    ManagedPdf,
    ManagedPdfScan,
)


def load_collection_rows(
    path: Path,
    *,
    storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
    limits: ReferenceIOLimits = RECONCILIATION_IO_LIMITS,
) -> EvidenceMapping[CollectionRowEvidence]:
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
        limits.max_text_bytes,
        "max_text_bytes",
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
                        field_value,
                        max_bytes=max_text_bytes,
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
                    for item in (row.get("source_bibliographies") or "").split(
                        ";"
                    )
                    if item
                )
                max_sources = _required_limit(
                    limits.max_candidates,
                    "max_candidates",
                )
                if len(sources) > max_sources:
                    raise ReferenceIOLimitError(
                        resource=(f"collection row {row_number} source list"),
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
    return EvidenceMapping(
        entries=tuple(sorted(result.items())),
        input_evidence=(
            ContentEvidence.from_bytes(
                role="collection-rows",
                filename="inputs/collection-rows.csv",
                content=content,
            ),
        ),
        root_preflights=(root_preflight,),
    )


def scan_managed_pdfs(
    directory: Path,
    *,
    storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
    source_discovery: Path | None = None,
    source_discovery_storage_class: RootStorageClass | None = None,
    limits: ReferenceIOLimits = RECONCILIATION_IO_LIMITS,
) -> ManagedPdfScan:
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
    if (source_discovery is None) != (source_discovery_storage_class is None):
        raise ValueError(
            "source discovery path and storage class must be supplied together"
        )
    historical: dict[str, tuple[str, tuple[str, ...]]]
    discovery_evidence: tuple[ContentEvidence, ...]
    if source_discovery is None:
        historical, discovery_evidence = {}, ()
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
    max_file_bytes = _required_limit(limits.max_file_bytes, "max_file_bytes")
    max_total_bytes = _required_limit(
        limits.max_total_bytes,
        "max_total_bytes",
    )
    for relative in relative_files:
        try:
            citekey = validate_citekey(Path(relative.name).stem)
            preflight = root.preflight_file(relative)
            if preflight.status is not PlaceholderStatus.ORDINARY_FILE:
                raise PlaceholderPreflightError(preflight)
            observation = root.observe_file(
                relative,
                max_bytes=max_file_bytes,
                prefix_bytes=5,
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
    return ManagedPdfScan(
        pdfs=tuple(pdfs),
        input_evidence=tuple(
            sorted(
                (*discovery_evidence, *asset_evidence),
                key=_content_evidence_key,
            )
        ),
        root_preflight=root.preflight_evidence,
        file_observations=tuple(
            sorted(
                file_observations,
                key=lambda item: item.relative_path or "",
            )
        ),
    )


def _load_source_discovery(
    path: Path | None,
    *,
    storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
    limits: ReferenceIOLimits = RECONCILIATION_IO_LIMITS,
) -> tuple[
    dict[str, tuple[str, tuple[str, ...]]],
    tuple[ContentEvidence, ...],
]:
    if path is None:
        return {}, ()
    try:
        content = read_path_bytes(
            path,
            label="source-discovery document",
            root_alias="source-discovery",
            storage_class=storage_class,
            placeholder_probe=placeholder_probe,
            max_bytes=_required_limit(
                limits.max_json_bytes,
                "max_json_bytes",
            ),
        )
    except PathLimitError as error:
        raise _limit_error(error, limits) from error
    try:
        text = content.decode("utf-8")
        validate_json_text_nesting(
            text,
            limits=limits,
            resource="source discovery JSON",
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
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or not isinstance(basis, str)
            or not basis
        ):
            raise CollectionReconciliationError(
                "source-discovery match identity is incomplete"
            )
        maximum_text = _required_limit(
            limits.max_text_bytes,
            "max_text_bytes",
        )
        basis_bytes = bounded_utf8_size(
            basis,
            max_bytes=maximum_text,
        )
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
    return result, (
        ContentEvidence.from_bytes(
            role="source-discovery",
            filename="inputs/source-discovery.json",
            content=content,
        ),
    )
