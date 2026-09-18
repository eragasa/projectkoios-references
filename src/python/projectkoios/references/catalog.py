from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from projectkoios.references.models import (
    AbstractRecord,
    BibliographyOccurrence,
    CitationCandidate,
    CitationEdge,
    ReferenceAlias,
    ReferenceRecord,
    ReviewMembership,
    SourceAssetRecord,
)
from projectkoios.references.path_safety import AuthorizedRoot

_SCHEMA_VERSION = 1
_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS catalog_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reference_records (
    citekey TEXT PRIMARY KEY,
    entry_type TEXT NOT NULL,
    title TEXT,
    authors_json TEXT NOT NULL,
    year TEXT,
    doi TEXT,
    isbn TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS reference_doi_unique
    ON reference_records(doi) WHERE doi IS NOT NULL;
CREATE TABLE IF NOT EXISTS reference_aliases (
    alias TEXT PRIMARY KEY,
    canonical_citekey TEXT NOT NULL,
    rationale TEXT NOT NULL,
    FOREIGN KEY(canonical_citekey) REFERENCES reference_records(citekey)
);
CREATE TABLE IF NOT EXISTS bibliography_occurrences (
    citekey TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_revision TEXT NOT NULL DEFAULT '',
    source_path TEXT NOT NULL,
    PRIMARY KEY(citekey, source_id, source_revision, source_path),
    FOREIGN KEY(citekey) REFERENCES reference_records(citekey)
);
CREATE TABLE IF NOT EXISTS source_assets (
    citekey TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    root_alias TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    rights_status TEXT NOT NULL,
    asset_status TEXT NOT NULL,
    PRIMARY KEY(citekey, sha256),
    FOREIGN KEY(citekey) REFERENCES reference_records(citekey)
);
CREATE TABLE IF NOT EXISTS review_memberships (
    collection_id TEXT NOT NULL,
    citekey TEXT NOT NULL,
    status TEXT NOT NULL,
    decision_note TEXT,
    PRIMARY KEY(collection_id, citekey),
    FOREIGN KEY(citekey) REFERENCES reference_records(citekey)
);
CREATE TABLE IF NOT EXISTS abstracts (
    citekey TEXT NOT NULL,
    provider TEXT NOT NULL,
    source_url TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    language TEXT,
    content_hash TEXT NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY(citekey, provider, content_hash),
    FOREIGN KEY(citekey) REFERENCES reference_records(citekey)
);
CREATE TABLE IF NOT EXISTS citation_candidates (
    candidate_id TEXT PRIMARY KEY,
    proposed_citekey TEXT,
    title TEXT,
    authors TEXT,
    year TEXT,
    doi TEXT,
    metadata_status TEXT NOT NULL,
    abstract_status TEXT NOT NULL,
    abstract TEXT
);
CREATE TABLE IF NOT EXISTS citation_edges (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    source_locator TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    PRIMARY KEY(source_id, target_id, relation, source_locator)
);
"""


class ReferenceConflictError(ValueError):
    """Raised instead of silently replacing conflicting accepted metadata."""


class ReferenceCatalog:
    """SQLite-backed working catalog with deterministic interchange inputs."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self._safe_path(create_parent=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            connection.execute(
                "INSERT OR REPLACE INTO catalog_metadata(key, value) "
                "VALUES('schema_version', ?)",
                (str(_SCHEMA_VERSION),),
            )

    def import_bibliography(
        self,
        records: Iterable[ReferenceRecord],
        occurrences: Iterable[BibliographyOccurrence],
    ) -> None:
        with self._connect() as connection:
            for record in records:
                values = (
                    record.entry_type,
                    record.title,
                    json.dumps(record.authors, ensure_ascii=False),
                    record.year,
                    record.doi,
                    record.isbn,
                )
                existing = connection.execute(
                    """
                    SELECT entry_type, title, authors_json, year, doi, isbn
                    FROM reference_records WHERE citekey = ?
                    """,
                    (record.citekey,),
                ).fetchone()
                if existing is not None and tuple(existing) != values:
                    raise ReferenceConflictError(
                        f"conflicting metadata for citekey {record.citekey}"
                    )
                if existing is None:
                    try:
                        connection.execute(
                            """
                            INSERT INTO reference_records(
                                citekey, entry_type, title, authors_json,
                                year, doi, isbn
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (record.citekey, *values),
                        )
                    except sqlite3.IntegrityError as error:
                        raise ReferenceConflictError(
                            "conflicting persistent identity for "
                            f"{record.citekey}"
                        ) from error
            for occurrence in occurrences:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO bibliography_occurrences(
                        citekey, source_id, source_revision, source_path
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        occurrence.citekey,
                        occurrence.source_id,
                        occurrence.source_revision or "",
                        occurrence.source_path,
                    ),
                )

    def add_alias(self, alias: ReferenceAlias) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO reference_aliases(
                    alias, canonical_citekey, rationale
                ) VALUES (?, ?, ?)
                """,
                (alias.alias, alias.canonical_citekey, alias.rationale),
            )

    def record_source_asset(self, asset: SourceAssetRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO source_assets(
                    citekey, sha256, byte_size, root_alias, relative_path,
                    rights_status, asset_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset.citekey,
                    asset.sha256,
                    asset.byte_size,
                    asset.root_alias,
                    asset.relative_path,
                    asset.rights_status,
                    asset.asset_status,
                ),
            )

    def set_review_membership(self, membership: ReviewMembership) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO review_memberships(
                    collection_id, citekey, status, decision_note
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(collection_id, citekey) DO UPDATE SET
                    status=excluded.status,
                    decision_note=excluded.decision_note
                """,
                (
                    membership.collection_id,
                    membership.citekey,
                    membership.status.value,
                    membership.decision_note,
                ),
            )

    def import_citation_graph(
        self,
        candidates: Iterable[CitationCandidate],
        edges: Iterable[CitationEdge],
    ) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO citation_candidates(
                    candidate_id, proposed_citekey, title, authors, year, doi,
                    metadata_status, abstract_status, abstract
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.candidate_id,
                        item.proposed_citekey,
                        item.title,
                        item.authors,
                        item.year,
                        item.doi,
                        item.metadata_status,
                        item.abstract_status,
                        item.abstract,
                    )
                    for item in candidates
                ],
            )
            connection.executemany(
                """
                INSERT OR REPLACE INTO citation_edges(
                    source_id, target_id, relation, source_locator,
                    verification_status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        edge.source_id,
                        edge.target_id,
                        edge.relation,
                        edge.source_locator,
                        edge.verification_status,
                    )
                    for edge in edges
                ],
            )

    def add_abstract(self, abstract: AbstractRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO abstracts(
                    citekey, provider, source_url, retrieved_at, language,
                    content_hash, text
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    abstract.citekey,
                    abstract.provider,
                    abstract.source_url,
                    abstract.retrieved_at,
                    abstract.language,
                    abstract.content_hash,
                    abstract.text,
                ),
            )

    def counts(self) -> dict[str, int]:
        tables = (
            "reference_records",
            "reference_aliases",
            "bibliography_occurrences",
            "source_assets",
            "review_memberships",
            "abstracts",
            "citation_candidates",
            "citation_edges",
        )
        with self._connect() as connection:
            return {
                table: int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {table}"  # noqa: S608
                    ).fetchone()[0]
                )
                for table in tables
            }

    def _connect(self) -> sqlite3.Connection:
        path = self._safe_path(create_parent=False)
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _safe_path(self, *, create_parent: bool) -> Path:
        root = (
            AuthorizedRoot.create(
                self.path.parent,
                label="reference catalog parent",
            )
            if create_parent
            else AuthorizedRoot.existing(
                self.path.parent,
                label="reference catalog parent",
            )
        )
        state = root.state(self.path.name)
        if state == "directory":
            raise ValueError("reference catalog path is a directory")
        return root.child_path(self.path.name)
