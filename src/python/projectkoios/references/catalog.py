from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from projectkoios.references.identity import (
    ReferenceCandidate,
    SourceBibliographyObservation,
)
from projectkoios.references.models import (
    AbstractRecord,
    CitationCandidate,
    CitationEdge,
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
CREATE TABLE IF NOT EXISTS source_bibliography_observations (
    observation_id TEXT PRIMARY KEY,
    authority_kind TEXT NOT NULL CHECK(
        authority_kind = 'source-bibliography-observation'
    ),
    observed_citekey TEXT NOT NULL,
    observation_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reference_candidates (
    candidate_id TEXT PRIMARY KEY,
    authority_kind TEXT NOT NULL CHECK(
        authority_kind = 'reference-candidate'
    ),
    lifecycle_status TEXT NOT NULL CHECK(
        lifecycle_status = 'unaccepted-candidate'
    ),
    proposed_citekey TEXT NOT NULL,
    citekey_status TEXT NOT NULL CHECK(
        citekey_status = 'proposed-noncanonical'
    ),
    candidate_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidate_source_observations (
    candidate_id TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    PRIMARY KEY(candidate_id, observation_id),
    FOREIGN KEY(candidate_id) REFERENCES reference_candidates(candidate_id),
    FOREIGN KEY(observation_id)
        REFERENCES source_bibliography_observations(observation_id)
);
CREATE TABLE IF NOT EXISTS candidate_source_assets (
    candidate_id TEXT NOT NULL,
    proposed_citekey TEXT NOT NULL,
    identity_status TEXT NOT NULL CHECK(
        identity_status = 'unaccepted-candidate'
    ),
    citekey_status TEXT NOT NULL CHECK(
        citekey_status = 'proposed-noncanonical'
    ),
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    root_alias TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    rights_status TEXT NOT NULL,
    asset_status TEXT NOT NULL,
    PRIMARY KEY(candidate_id, sha256),
    FOREIGN KEY(candidate_id) REFERENCES reference_candidates(candidate_id)
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


class CandidateConflictError(ValueError):
    """Raised instead of silently replacing candidate metadata."""


class ReferenceCatalog:
    """Provisional SQLite projection; it carries no canonical authority."""

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

    def import_candidates(
        self,
        candidates: Iterable[ReferenceCandidate],
        observations: Iterable[SourceBibliographyObservation],
    ) -> None:
        """Project observed candidates without granting canonical authority."""
        candidate_values = tuple(candidates)
        observation_values = tuple(observations)
        with self._connect() as connection:
            for observation in observation_values:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO source_bibliography_observations(
                        observation_id, authority_kind, observed_citekey,
                        observation_json
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        observation.observation_id,
                        observation.authority_kind,
                        observation.observed_citekey,
                        observation.to_json(),
                    ),
                )
            for record in candidate_values:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO reference_candidates(
                        candidate_id, authority_kind, lifecycle_status,
                        proposed_citekey, citekey_status, candidate_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.candidate_id,
                        record.authority_kind,
                        record.lifecycle_status,
                        record.proposed_citekey,
                        record.citekey_status,
                        record.to_json(),
                    ),
                )
                for observation_id in record.source_observation_ids:
                    try:
                        connection.execute(
                            """
                            INSERT OR IGNORE INTO candidate_source_observations(
                                candidate_id, observation_id
                            ) VALUES (?, ?)
                            """,
                            (record.candidate_id, observation_id),
                        )
                    except sqlite3.IntegrityError as error:
                        raise CandidateConflictError(
                            "candidate source observation is unavailable"
                        ) from error
            for record in candidate_values:
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
                    (record.proposed_citekey,),
                ).fetchone()
                if existing is not None and tuple(existing) != values:
                    raise CandidateConflictError(
                        "conflicting candidate metadata for proposed citekey "
                        f"{record.proposed_citekey}"
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
                            (record.proposed_citekey, *values),
                        )
                    except sqlite3.IntegrityError as error:
                        raise CandidateConflictError(
                            "conflicting candidate identifier for "
                            f"{record.proposed_citekey}"
                        ) from error
            for occurrence in observation_values:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO bibliography_occurrences(
                        citekey, source_id, source_revision, source_path
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        occurrence.observed_citekey,
                        occurrence.source_id,
                        occurrence.asserted_source_revision or "",
                        occurrence.source_path,
                    ),
                )

    def record_source_asset(self, asset: SourceAssetRecord) -> None:
        with self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO candidate_source_assets(
                        candidate_id, proposed_citekey, identity_status,
                        citekey_status, sha256, byte_size, root_alias,
                        relative_path, rights_status, asset_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        asset.candidate_id,
                        asset.proposed_citekey,
                        asset.identity_status,
                        asset.citekey_status,
                        asset.sha256,
                        asset.byte_size,
                        asset.root_alias,
                        asset.relative_path,
                        asset.rights_status,
                        asset.asset_status,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise CandidateConflictError(
                    "source asset candidate is unavailable"
                ) from error
            connection.execute(
                """
                INSERT OR REPLACE INTO source_assets(
                    citekey, sha256, byte_size, root_alias, relative_path,
                    rights_status, asset_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset.proposed_citekey,
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
        projections = (
            ("candidate_records", "reference_candidates"),
            ("unprovenanced_alias_rows", "reference_aliases"),
            (
                "bibliography_observations",
                "source_bibliography_observations",
            ),
            ("source_assets", "candidate_source_assets"),
            ("review_memberships", "review_memberships"),
            ("abstracts", "abstracts"),
            ("citation_candidates", "citation_candidates"),
            ("citation_edges", "citation_edges"),
        )
        with self._connect() as connection:
            return {
                label: int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {table}"  # noqa: S608
                    ).fetchone()[0]
                )
                for label, table in projections
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
