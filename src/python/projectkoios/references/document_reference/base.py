"""Shared immutable base for document/reference data objects."""

from __future__ import annotations

import re
from abc import ABC
from urllib.parse import urlsplit

from projectkoios.base import DataObject

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]{0,199}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_RECEIPT_ID = re.compile(r"document-receipt:sha256:[0-9a-f]{64}")
_BINDING_ID = re.compile(r"reference-document-binding:sha256:[0-9a-f]{64}")
_ENTRY_TYPE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")


class AbstractDocumentReferenceDataObject(DataObject, ABC):
    """Own shared bounded-value invariants for document/reference objects."""

    __slots__ = ()

    @staticmethod
    def _validate_identifier(value: str, *, field: str) -> str:
        if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
            raise ValueError(
                f"{field} must be 1-200 ASCII identifier characters"
            )
        return value

    @staticmethod
    def _validate_sha256(value: str, *, field: str = "sha256") -> str:
        if type(value) is not str or _SHA256.fullmatch(value) is None:
            raise ValueError(f"{field} must be a lowercase SHA-256 digest")
        return value

    @staticmethod
    def _validate_receipt_id(value: str) -> str:
        if type(value) is not str or _RECEIPT_ID.fullmatch(value) is None:
            raise ValueError("receipt_id is not a document receipt identity")
        return value

    @staticmethod
    def _validate_binding_id(value: str) -> str:
        if type(value) is not str or _BINDING_ID.fullmatch(value) is None:
            raise ValueError("binding_id is not a reference binding identity")
        return value

    @staticmethod
    def _validate_entry_type(value: str) -> str:
        if type(value) is not str or _ENTRY_TYPE.fullmatch(value) is None:
            raise ValueError("entry_type must be a bounded BibTeX entry type")
        return value

    @staticmethod
    def _validate_source_link(value: str | None) -> str | None:
        if value is None:
            return None
        if type(value) is not str or not 1 <= len(value) <= 2048:
            raise ValueError("source_link must contain 1-2048 characters")
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError(
                "source_link must be an unauthenticated HTTP(S) URL"
            )
        return value
