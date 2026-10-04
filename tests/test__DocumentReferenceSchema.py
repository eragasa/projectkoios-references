from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from projectkoios.references.adapters.sql.sqlite import (
    document_reference_schema,
)

from tools.render_document_reference_schema import (
    render_document_reference_schema,
)

_REPOSITORY = Path(__file__).resolve().parents[1]
DocumentReferenceSchema = document_reference_schema.DocumentReferenceSchema


def _database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    DocumentReferenceSchema.initialize(connection)
    return connection


def _reference(connection: sqlite3.Connection, citekey: str) -> None:
    connection.execute(
        "INSERT INTO reference_records(citekey, bibtex_entry) VALUES (?, ?)",
        (citekey, f"@article{{{citekey}, title={{Sanitized title}}}}"),
    )


def test__document_reference_schema__documentation_is_generated() -> None:
    documentation = _REPOSITORY / "docs" / "document-reference-schema.md"

    assert documentation.read_text(encoding="utf-8") == (
        render_document_reference_schema()
    )


def test__document_reference_schema__bootstrap_verified_empty_database() -> (
    None
):
    connection = _database()

    DocumentReferenceSchema.require_supported(connection)
    for _, query, expected_rows in DocumentReferenceSchema.VERIFICATION_QUERIES:
        assert tuple(connection.execute(query).fetchall()) == expected_rows


def test__document_reference_schema__rejects_existing_schema() -> None:
    connection = _database()

    with pytest.raises(ValueError, match="not empty"):
        DocumentReferenceSchema.initialize(connection)

    version_only = sqlite3.connect(":memory:")
    version_only.execute("PRAGMA user_version = 99")
    with pytest.raises(ValueError, match="not empty"):
        DocumentReferenceSchema.initialize(version_only)
    version_only.close()


def test__document_reference_schema__separates_requirement_and_binding() -> (
    None
):
    connection = _database()
    _reference(connection, "requiredKey")
    _reference(connection, "webOnlyKey")
    connection.execute(
        "INSERT INTO reference_collections VALUES (?, ?, ?)",
        ("ksdft2effmass", "sanitized-monograph", "revision-1"),
    )
    connection.executemany(
        "INSERT INTO reference_collection_memberships VALUES (?, ?, ?)",
        (
            ("ksdft2effmass", "requiredKey", "required"),
            ("ksdft2effmass", "webOnlyKey", "not-applicable"),
        ),
    )
    digest = "a" * 64
    connection.execute(
        "INSERT INTO documents VALUES (?, ?, ?)",
        (digest, 20, "application/pdf"),
    )

    assert connection.execute(
        "SELECT citekey, pdf_requirement "
        "FROM reference_collection_memberships ORDER BY citekey"
    ).fetchall() == [
        ("requiredKey", "required"),
        ("webOnlyKey", "not-applicable"),
    ]
    assert connection.execute(
        "SELECT COUNT(*) FROM reference_document_bindings"
    ).fetchone() == (0,)

    connection.execute(
        "INSERT INTO reference_document_bindings VALUES (?, ?, ?, ?)",
        (
            "reference-document-binding:sha256:" + "b" * 64,
            "requiredKey",
            digest,
            "explicit-reference-document-selection",
        ),
    )

    assert connection.execute(
        "SELECT citekey, document_sha256 FROM reference_document_bindings"
    ).fetchall() == [("requiredKey", digest)]


def test__document_reference_schema__preserves_source_observations() -> None:
    connection = _database()
    digest = "a" * 64
    connection.execute(
        "INSERT INTO documents VALUES (?, ?, ?)",
        (digest, 20, "application/pdf"),
    )
    connection.executemany(
        "INSERT INTO document_receipts VALUES (?, ?, ?)",
        (
            (
                "document-receipt:sha256:" + "b" * 64,
                digest,
                "https://example.test/source-one.pdf",
            ),
            (
                "document-receipt:sha256:" + "c" * 64,
                digest,
                "https://example.test/source-two.pdf",
            ),
        ),
    )

    assert connection.execute(
        "SELECT source_link FROM document_receipts ORDER BY source_link"
    ).fetchall() == [
        ("https://example.test/source-one.pdf",),
        ("https://example.test/source-two.pdf",),
    ]
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO document_receipts VALUES (?, ?, ?)",
            (
                "document-receipt:sha256:" + "d" * 64,
                digest,
                "https://example.test/source-one.pdf",
            ),
        )


def test__document_reference_schema__enforces_one_to_one_bindings() -> None:
    connection = _database()
    _reference(connection, "firstKey")
    _reference(connection, "secondKey")
    connection.executemany(
        "INSERT INTO documents VALUES (?, ?, ?)",
        (("a" * 64, 20, "application/pdf"), ("b" * 64, 21, "application/pdf")),
    )
    connection.execute(
        "INSERT INTO reference_document_bindings VALUES (?, ?, ?, ?)",
        (
            "reference-document-binding:sha256:" + "c" * 64,
            "firstKey",
            "a" * 64,
            "explicit-reference-document-selection",
        ),
    )

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO reference_document_bindings VALUES (?, ?, ?, ?)",
            (
                "reference-document-binding:sha256:" + "d" * 64,
                "firstKey",
                "b" * 64,
                "explicit-reference-document-selection",
            ),
        )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO reference_document_bindings VALUES (?, ?, ?, ?)",
            (
                "reference-document-binding:sha256:" + "e" * 64,
                "secondKey",
                "a" * 64,
                "explicit-reference-document-selection",
            ),
        )
