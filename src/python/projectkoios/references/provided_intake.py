from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

_MAX_PDF_BYTES = 100_000_000
_SHA256 = re.compile(r"[0-9a-f]{64}")
_RECEIPT = re.compile(r"provided-reference:sha256:([0-9a-f]{64})")


class ProvidedReferenceStatus(StrEnum):
    RECEIVED_NOT_INGESTED = "RECEIVED_NOT_INGESTED"
    INGESTED_AUTOMATED_UNREVIEWED = "INGESTED_AUTOMATED_UNREVIEWED"


class ProvidedReferenceIntakeError(RuntimeError):
    pass


class InvalidProvidedReference(ValueError):
    pass


@dataclass(frozen=True)
class ProvidedReference:
    receipt_id: str
    claim_id: str
    citation_label: str
    doi_or_url: str | None
    note: str
    source_sha256: str
    byte_length: int
    status: ProvidedReferenceStatus
    received_at_utc: str
    latest_generation: str | None = None
    source_id: str | None = None
    review_boundary: str | None = None
    duplicate: bool = False


class ProvidedReferenceIntakeStore:
    """Private immutable PDF intake with separate ingestion disposition."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser()
        if self.root.is_symlink():
            raise ProvidedReferenceIntakeError(
                "provided-reference root must not be a symlink"
            )

    def receive(
        self,
        *,
        claim_id: str,
        citation_label: str,
        doi_or_url: str | None,
        note: str,
        pdf_bytes: bytes,
        received_at_utc: str | None = None,
    ) -> ProvidedReference:
        claim_id = _required_string(claim_id, "claim identity", 128)
        citation_label = _required_string(citation_label, "citation label", 128)
        doi_or_url = _optional_string(doi_or_url, "DOI or URL", 1_000)
        note = _required_string(note, "reference note", 4_000, allow_empty=True)
        if not pdf_bytes or len(pdf_bytes) > _MAX_PDF_BYTES:
            raise InvalidProvidedReference(
                "reference PDF must be between 1 and 100000000 bytes"
            )
        if not pdf_bytes.startswith(b"%PDF-"):
            raise InvalidProvidedReference(
                "provided reference does not have a PDF header"
            )
        source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
        identity = {
            "schema": "koios.provided-reference-identity.v1",
            "claim_id": claim_id,
            "citation_label": citation_label,
            "doi_or_url": doi_or_url,
            "note": note,
            "source_sha256": source_sha256,
            "byte_length": len(pdf_bytes),
        }
        receipt_digest = hashlib.sha256(_canonical_bytes(identity)).hexdigest()
        receipt_id = f"provided-reference:sha256:{receipt_digest}"
        self._prepare_layout(source_sha256)
        object_path = self._object_path(source_sha256)
        if object_path.exists():
            _regular_file(object_path, "provided-reference object")
            if (
                hashlib.sha256(object_path.read_bytes()).hexdigest()
                != source_sha256
            ):
                raise ProvidedReferenceIntakeError(
                    "provided-reference object failed its hash check"
                )
        else:
            _atomic_write(object_path, pdf_bytes)
        record_path = self._record_path(receipt_digest)
        if record_path.exists():
            return self._parse_reference(
                _read_json(record_path, "provided-reference record"),
                duplicate=True,
            )
        record = {
            "schema": "koios.provided-reference.v1",
            "receipt_id": receipt_id,
            "claim_id": claim_id,
            "citation_label": citation_label,
            "doi_or_url": doi_or_url,
            "note": note,
            "source_sha256": source_sha256,
            "byte_length": len(pdf_bytes),
            "status": ProvidedReferenceStatus.RECEIVED_NOT_INGESTED.value,
            "received_at_utc": received_at_utc or datetime.now(UTC).isoformat(),
        }
        _atomic_write(record_path, _canonical_bytes(record))
        return self._parse_reference(record)

    def list(self) -> tuple[ProvidedReference, ...]:
        records = self.root / "records"
        if not records.exists():
            return ()
        _directory(records, "provided-reference records")
        dispositions = self._dispositions()
        result: list[ProvidedReference] = []
        for path in sorted(records.glob("*.json")):
            record = _read_json(path, "provided-reference record")
            receipt_id = _record_string(record, "receipt_id")
            match = _RECEIPT.fullmatch(receipt_id)
            if match is None or match.group(1) != path.stem:
                raise ProvidedReferenceIntakeError(
                    "provided-reference record identity is invalid"
                )
            result.append(
                self._parse_reference(
                    record,
                    disposition=dispositions.get(receipt_id),
                )
            )
        result.sort(key=lambda item: item.received_at_utc, reverse=True)
        return tuple(result)

    def record_ingestion(
        self,
        *,
        receipt_id: str,
        source_id: str,
        latest_generation: str,
        affected_claims: tuple[str, ...],
        review_boundary: str,
        recorded_at_utc: str | None = None,
    ) -> ProvidedReference:
        match = _RECEIPT.fullmatch(receipt_id)
        if match is None:
            raise InvalidProvidedReference("receipt identity is invalid")
        record_path = self._record_path(match.group(1))
        record = _read_json(record_path, "provided-reference record")
        source_sha256 = _record_string(record, "source_sha256")
        if source_id != f"rag:sha256:{source_sha256}":
            raise InvalidProvidedReference(
                "ingested source identity does not match received PDF"
            )
        latest_generation = _required_string(
            latest_generation, "latest generation", 256
        )
        review_boundary = _required_string(
            review_boundary, "review boundary", 2_000
        )
        if not affected_claims or len(affected_claims) > 100:
            raise InvalidProvidedReference(
                "affected claims must contain 1 to 100"
            )
        claims = tuple(
            _required_string(item, "affected claim", 128)
            for item in affected_claims
        )
        if len(set(claims)) != len(claims):
            raise InvalidProvidedReference("affected claims must be unique")
        if receipt_id in self._dispositions():
            raise ProvidedReferenceIntakeError(
                "receipt already has an ingestion disposition"
            )
        disposition = {
            "schema": "koios.provided-reference-disposition.v1",
            "receipt_id": receipt_id,
            "source_id": source_id,
            "status": (
                ProvidedReferenceStatus.INGESTED_AUTOMATED_UNREVIEWED.value
            ),
            "latest_generation": latest_generation,
            "affected_claims": list(claims),
            "review_boundary": review_boundary,
            "recorded_at_utc": recorded_at_utc or datetime.now(UTC).isoformat(),
        }
        payload = _canonical_bytes(disposition)
        digest = hashlib.sha256(payload).hexdigest()
        _private_directory(self.root / "dispositions")
        _atomic_write(self.root / "dispositions" / f"{digest}.json", payload)
        return self._parse_reference(record, disposition=disposition)

    def object_path(self, source_sha256: str) -> Path:
        if _SHA256.fullmatch(source_sha256) is None:
            raise InvalidProvidedReference("source hash is invalid")
        path = self._object_path(source_sha256)
        _regular_file(path, "provided-reference object")
        if hashlib.sha256(path.read_bytes()).hexdigest() != source_sha256:
            raise ProvidedReferenceIntakeError(
                "provided-reference object failed its hash check"
            )
        return path

    def _prepare_layout(self, source_sha256: str) -> None:
        _private_directory(self.root)
        _private_directory(self.root / "objects")
        _private_directory(self.root / "objects" / source_sha256[:2])
        _private_directory(self.root / "records")

    def _record_path(self, digest: str) -> Path:
        return self.root / "records" / f"{digest}.json"

    def _object_path(self, source_sha256: str) -> Path:
        return (
            self.root / "objects" / source_sha256[:2] / f"{source_sha256}.pdf"
        )

    def _dispositions(self) -> dict[str, dict[str, Any]]:
        path = self.root / "dispositions"
        if not path.exists():
            return {}
        _directory(path, "provided-reference dispositions")
        result: dict[str, dict[str, Any]] = {}
        for record_path in sorted(path.glob("*.json")):
            disposition = _read_json(
                record_path, "provided-reference disposition"
            )
            receipt_id = _record_string(disposition, "receipt_id")
            if receipt_id in result:
                raise ProvidedReferenceIntakeError(
                    "provided-reference disposition is duplicated"
                )
            status = ProvidedReferenceStatus(
                _record_string(disposition, "status")
            )
            if (
                status
                is not ProvidedReferenceStatus.INGESTED_AUTOMATED_UNREVIEWED
            ):
                raise ProvidedReferenceIntakeError(
                    "provided-reference disposition status is invalid"
                )
            _record_string(disposition, "latest_generation")
            result[receipt_id] = disposition
        return result

    def _parse_reference(
        self,
        record: dict[str, Any],
        *,
        disposition: dict[str, Any] | None = None,
        duplicate: bool = False,
    ) -> ProvidedReference:
        if record.get("schema") != "koios.provided-reference.v1":
            raise ProvidedReferenceIntakeError(
                "provided-reference schema is unsupported"
            )
        source_sha256 = _record_string(record, "source_sha256")
        if _SHA256.fullmatch(source_sha256) is None:
            raise ProvidedReferenceIntakeError(
                "provided-reference hash is invalid"
            )
        receipt_id = _record_string(record, "receipt_id")
        identity = {
            "schema": "koios.provided-reference-identity.v1",
            "claim_id": _record_string(record, "claim_id"),
            "citation_label": _record_string(record, "citation_label"),
            "doi_or_url": _record_optional_string(record, "doi_or_url"),
            "note": _record_string(record, "note", allow_empty=True),
            "source_sha256": source_sha256,
            "byte_length": _positive_int(record, "byte_length"),
        }
        expected_receipt = (
            "provided-reference:sha256:"
            + hashlib.sha256(_canonical_bytes(identity)).hexdigest()
        )
        if receipt_id != expected_receipt:
            raise ProvidedReferenceIntakeError(
                "provided-reference receipt failed its identity check"
            )
        source_id = (
            None
            if disposition is None
            else _record_optional_string(disposition, "source_id")
        )
        if source_id is not None and source_id != f"rag:sha256:{source_sha256}":
            raise ProvidedReferenceIntakeError(
                "provided-reference disposition source does not match"
            )
        status_record = disposition or record
        return ProvidedReference(
            receipt_id=receipt_id,
            claim_id=_record_string(record, "claim_id"),
            citation_label=_record_string(record, "citation_label"),
            doi_or_url=_record_optional_string(record, "doi_or_url"),
            note=_record_string(record, "note", allow_empty=True),
            source_sha256=source_sha256,
            byte_length=_positive_int(record, "byte_length"),
            status=ProvidedReferenceStatus(
                _record_string(status_record, "status")
            ),
            received_at_utc=_record_string(record, "received_at_utc"),
            latest_generation=(
                None
                if disposition is None
                else _record_string(disposition, "latest_generation")
            ),
            source_id=source_id,
            review_boundary=(
                None
                if disposition is None
                else _record_optional_string(disposition, "review_boundary")
            ),
            duplicate=duplicate,
        )


def _required_string(
    value: object,
    label: str,
    maximum: int,
    *,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise InvalidProvidedReference(f"{label} must be text")
    normalized = value.strip()
    if (not normalized and not allow_empty) or len(normalized) > maximum:
        raise InvalidProvidedReference(f"{label} is invalid")
    if any(ord(character) < 32 for character in normalized):
        raise InvalidProvidedReference(f"{label} contains a control character")
    return normalized


def _optional_string(value: object, label: str, maximum: int) -> str | None:
    if value is None or value == "":
        return None
    return _required_string(value, label, maximum)


def _record_string(
    record: dict[str, Any], key: str, *, allow_empty: bool = False
) -> str:
    value = record.get(key)
    if not isinstance(value, str) or (not value and not allow_empty):
        raise ProvidedReferenceIntakeError(f"record field {key} is invalid")
    return value


def _record_optional_string(record: dict[str, Any], key: str) -> str | None:
    value = record.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ProvidedReferenceIntakeError(f"record field {key} is invalid")
    return value


def _positive_int(record: dict[str, Any], key: str) -> int:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProvidedReferenceIntakeError(f"record field {key} is invalid")
    return value


def _private_directory(path: Path) -> None:
    if path.is_symlink():
        raise ProvidedReferenceIntakeError(
            "provided-reference directory must not be a symlink"
        )
    if path.exists() and not path.is_dir():
        raise ProvidedReferenceIntakeError(
            "provided-reference directory is unavailable"
        )
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)


def _directory(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ProvidedReferenceIntakeError(f"{label} is unavailable")


def _regular_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ProvidedReferenceIntakeError(f"{label} is unavailable")


def _atomic_write(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise ProvidedReferenceIntakeError(
            "provided-reference destination already exists"
        )
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ProvidedReferenceIntakeError(
            "provided-reference destination is unavailable"
        )
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise ProvidedReferenceIntakeError(
            "provided-reference temporary path already exists"
        )
    with temporary.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    _regular_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProvidedReferenceIntakeError(f"{label} is invalid") from error
    if not isinstance(value, dict):
        raise ProvidedReferenceIntakeError(f"{label} must be an object")
    return value
