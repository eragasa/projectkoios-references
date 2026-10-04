"""Authoritative empty SQLite schema for documents and references."""

from __future__ import annotations

import sqlite3
from typing import final


@final
class DocumentReferenceSchema:
    """Define and verify a new parallel document/reference database."""

    VERSION = 1
    TABLE_NAMES = (
        "document_receipts",
        "documents",
        "reference_collection_memberships",
        "reference_collections",
        "reference_document_bindings",
        "reference_records",
    )
    RULES = (
        "A document is identified by the SHA-256 digest of its PDF bytes.",
        "A document may exist without a reference or collection membership.",
        "Each PDF receipt retains its supplied source link independently.",
        "The BibTeX citekey is the reference primary key.",
        "A collection records source and revision provenance.",
        (
            "Each collection member declares whether a PDF is required or "
            "not applicable."
        ),
        "A reference and document may have at most one neutral binding each.",
        (
            "A binding never accepts metadata, rights, scientific support, "
            "or publication."
        ),
        "Existing rows and PDF objects are never replaced implicitly.",
        "The schema-5 catalog remains authoritative until an explicit cutover.",
    )
    BOOTSTRAP_SQL = """\
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

CREATE TABLE documents (
    sha256 TEXT PRIMARY KEY NOT NULL,
    byte_size INTEGER NOT NULL,
    media_type TEXT NOT NULL,
    CHECK(length(sha256) = 64),
    CHECK(sha256 NOT GLOB '*[^0-9a-f]*'),
    CHECK(typeof(byte_size) = 'integer'),
    CHECK(byte_size BETWEEN 1 AND 100000000),
    CHECK(media_type = 'application/pdf')
) STRICT;

CREATE TABLE document_receipts (
    receipt_id TEXT PRIMARY KEY NOT NULL,
    document_sha256 TEXT NOT NULL,
    source_link TEXT,
    CHECK(length(receipt_id) = 88),
    CHECK(substr(receipt_id, 1, 24) = 'document-receipt:sha256:'),
    CHECK(substr(receipt_id, 25) NOT GLOB '*[^0-9a-f]*'),
    CHECK(source_link IS NULL OR length(source_link) BETWEEN 1 AND 2048),
    UNIQUE(document_sha256, source_link),
    FOREIGN KEY(document_sha256) REFERENCES documents(sha256)
) STRICT;

CREATE TABLE reference_records (
    citekey TEXT PRIMARY KEY NOT NULL,
    bibtex_entry TEXT NOT NULL,
    CHECK(length(citekey) BETWEEN 1 AND 200),
    CHECK(citekey GLOB '[A-Za-z0-9]*'),
    CHECK(citekey NOT GLOB '*[^A-Za-z0-9._:+-]*'),
    CHECK(length(bibtex_entry) BETWEEN 1 AND 262144)
) STRICT;

CREATE TABLE reference_collections (
    collection_id TEXT PRIMARY KEY NOT NULL,
    source_id TEXT NOT NULL,
    source_revision TEXT NOT NULL,
    CHECK(length(collection_id) BETWEEN 1 AND 200),
    CHECK(collection_id GLOB '[A-Za-z0-9]*'),
    CHECK(collection_id NOT GLOB '*[^A-Za-z0-9._:+-]*'),
    CHECK(length(source_id) BETWEEN 1 AND 1000),
    CHECK(length(source_revision) BETWEEN 1 AND 200)
) STRICT;

CREATE TABLE reference_collection_memberships (
    collection_id TEXT NOT NULL,
    citekey TEXT NOT NULL,
    pdf_requirement TEXT NOT NULL,
    PRIMARY KEY(collection_id, citekey),
    CHECK(pdf_requirement IN ('required', 'not-applicable')),
    FOREIGN KEY(collection_id)
        REFERENCES reference_collections(collection_id),
    FOREIGN KEY(citekey) REFERENCES reference_records(citekey)
) STRICT;

CREATE TABLE reference_document_bindings (
    binding_id TEXT PRIMARY KEY NOT NULL,
    citekey TEXT NOT NULL UNIQUE,
    document_sha256 TEXT NOT NULL UNIQUE,
    linkage_basis TEXT NOT NULL,
    CHECK(length(binding_id) = 98),
    CHECK(substr(binding_id, 1, 34) = 'reference-document-binding:sha256:'),
    CHECK(substr(binding_id, 35) NOT GLOB '*[^0-9a-f]*'),
    CHECK(linkage_basis IN (
        'explicit-reference-document-selection',
        'verified-local-evidence-import'
    )),
    FOREIGN KEY(citekey) REFERENCES reference_records(citekey),
    FOREIGN KEY(document_sha256) REFERENCES documents(sha256)
) STRICT;

PRAGMA user_version = 1;
COMMIT;
"""

    @classmethod
    def initialize(cls, connection: sqlite3.Connection) -> None:
        """Create the schema only in a database with no schema objects."""
        existing = connection.execute(
            "SELECT name FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall()
        version = connection.execute("PRAGMA user_version").fetchone()
        if existing or version != (0,):
            raise ValueError("document/reference database is not empty")
        connection.executescript(cls.BOOTSTRAP_SQL)
        cls.require_supported(connection)

    @classmethod
    def require_supported(
        cls,
        connection: sqlite3.Connection,
        *,
        check_integrity: bool = True,
    ) -> None:
        """Require the exact schema and optional stored-row integrity."""
        if type(check_integrity) is not bool:
            raise ValueError("check_integrity must be a bool")
        version = connection.execute("PRAGMA user_version").fetchone()
        if version != (cls.VERSION,):
            raise ValueError("unsupported document/reference schema version")
        actual = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_schema "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        memory = sqlite3.connect(":memory:")
        try:
            memory.executescript(cls.BOOTSTRAP_SQL)
            expected = memory.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_schema "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
            ).fetchall()
        finally:
            memory.close()
        if actual != expected:
            raise ValueError(
                "document/reference schema differs from supported schema"
            )
        if check_integrity:
            if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ValueError(
                    "document/reference database integrity check failed"
                )
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("document/reference foreign-key check failed")

    VERIFICATION_QUERIES = (
        ("schema version", "PRAGMA user_version;", ((1,),)),
        (
            "application tables",
            (
                "SELECT name, type FROM sqlite_schema "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY name;"
            ),
            tuple((name, "table") for name in TABLE_NAMES),
        ),
        ("empty document table", "SELECT COUNT(*) FROM documents;", ((0,),)),
        (
            "empty receipt table",
            "SELECT COUNT(*) FROM document_receipts;",
            ((0,),),
        ),
        (
            "empty reference table",
            "SELECT COUNT(*) FROM reference_records;",
            ((0,),),
        ),
        (
            "empty collection table",
            "SELECT COUNT(*) FROM reference_collections;",
            ((0,),),
        ),
        (
            "empty membership table",
            "SELECT COUNT(*) FROM reference_collection_memberships;",
            ((0,),),
        ),
        (
            "empty binding table",
            "SELECT COUNT(*) FROM reference_document_bindings;",
            ((0,),),
        ),
        ("database integrity", "PRAGMA quick_check;", (("ok",),)),
        ("foreign-key integrity", "PRAGMA foreign_key_check;", ()),
    )
