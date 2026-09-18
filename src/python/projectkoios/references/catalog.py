from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from projectkoios.references.graph import (
    CitationCandidate,
    CitationEdge,
    CitationGraph,
    CitationGraphError,
    CitationSourceObservation,
)
from projectkoios.references.identity import (
    ReferenceCandidate,
    SourceBibliographyObservation,
)
from projectkoios.references.models import (
    AbstractRecord,
    ReviewMembership,
    SourceAssetRecord,
)
from projectkoios.references.path_safety import AuthorizedRoot

CATALOG_SCHEMA_VERSION = 3
SUPPORTED_CATALOG_SCHEMA_VERSIONS = (CATALOG_SCHEMA_VERSION,)

_SCHEMA_METADATA_KEYS = frozenset({"schema_version", "schema_fingerprint"})
_LEGACY_METADATA_KEYS = frozenset({"schema_version"})
_AUTHORITY_BOUNDARY = "non-authoritative-rebuildable-working-projection"

_PROTOTYPE_V1_FINGERPRINT = (
    "catalog-schema:sha256:"
    "5714c33eba9eb9638c0735dff5824058d7c77115a3a5c62f97486e0da41d771b"
)
_IDENTITY_V1_FINGERPRINT = (
    "catalog-schema:sha256:"
    "b6280d710df8e1cabdcdec99847a927135a49b9e833d3cb84c5e9bf44ce845c8"
)
_PUBLISHED_V2_FINGERPRINT = (
    "catalog-schema:sha256:"
    "2e8db847387f06a003f56c375694000eee5be7edd32d4e7f0712267d1e3d0bc5"
)

_TARGET_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE catalog_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE source_bibliography_observations (
        observation_id TEXT PRIMARY KEY,
        record_schema_version INTEGER NOT NULL CHECK(
            record_schema_version = 1
        ),
        authority_kind TEXT NOT NULL CHECK(
            authority_kind = 'source-bibliography-observation'
        ),
        source_id TEXT NOT NULL,
        asserted_source_revision TEXT,
        source_path TEXT NOT NULL,
        bibliography_sha256 TEXT NOT NULL,
        bibliography_byte_size INTEGER NOT NULL CHECK(
            bibliography_byte_size > 0
        ),
        entry_index INTEGER NOT NULL CHECK(entry_index >= 0),
        observed_citekey TEXT NOT NULL,
        verbatim_entry TEXT NOT NULL,
        parser_name TEXT NOT NULL,
        parser_version TEXT NOT NULL,
        observation_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE reference_candidates (
        candidate_id TEXT PRIMARY KEY,
        record_schema_version INTEGER NOT NULL CHECK(
            record_schema_version = 1
        ),
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
        entry_type TEXT NOT NULL,
        title TEXT,
        authors_json TEXT NOT NULL,
        year TEXT,
        doi TEXT,
        isbn TEXT,
        url TEXT,
        eprint TEXT,
        generator_name TEXT NOT NULL,
        generator_version TEXT NOT NULL,
        candidate_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE candidate_source_observations (
        candidate_id TEXT NOT NULL,
        observation_id TEXT NOT NULL,
        PRIMARY KEY(candidate_id, observation_id),
        FOREIGN KEY(candidate_id) REFERENCES reference_candidates(candidate_id),
        FOREIGN KEY(observation_id)
            REFERENCES source_bibliography_observations(observation_id)
    )
    """,
    """
    CREATE TABLE candidate_source_assets (
        candidate_id TEXT NOT NULL,
        proposed_citekey TEXT NOT NULL,
        identity_status TEXT NOT NULL CHECK(
            identity_status = 'unaccepted-candidate'
        ),
        citekey_status TEXT NOT NULL CHECK(
            citekey_status = 'proposed-noncanonical'
        ),
        sha256 TEXT NOT NULL,
        byte_size INTEGER NOT NULL CHECK(
            typeof(byte_size) = 'integer' AND byte_size >= 0
        ),
        root_alias TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        rights_status TEXT NOT NULL,
        asset_status TEXT NOT NULL,
        PRIMARY KEY(candidate_id, sha256),
        FOREIGN KEY(candidate_id) REFERENCES reference_candidates(candidate_id)
    )
    """,
    """
    CREATE TABLE legacy_reference_records (
        citekey TEXT PRIMARY KEY,
        entry_type TEXT NOT NULL,
        title TEXT,
        authors_json TEXT NOT NULL,
        year TEXT,
        doi TEXT,
        isbn TEXT
    )
    """,
    """
    CREATE UNIQUE INDEX legacy_reference_doi_unique
        ON legacy_reference_records(doi) WHERE doi IS NOT NULL
    """,
    """
    CREATE TABLE legacy_reference_aliases (
        alias TEXT PRIMARY KEY,
        canonical_citekey TEXT NOT NULL,
        rationale TEXT NOT NULL,
        FOREIGN KEY(canonical_citekey)
            REFERENCES legacy_reference_records(citekey)
    )
    """,
    """
    CREATE TABLE legacy_bibliography_occurrences (
        citekey TEXT NOT NULL,
        source_id TEXT NOT NULL,
        source_revision TEXT NOT NULL DEFAULT '',
        source_path TEXT NOT NULL,
        PRIMARY KEY(citekey, source_id, source_revision, source_path),
        FOREIGN KEY(citekey) REFERENCES legacy_reference_records(citekey)
    )
    """,
    """
    CREATE TABLE legacy_source_assets (
        citekey TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        byte_size INTEGER NOT NULL,
        root_alias TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        rights_status TEXT NOT NULL,
        asset_status TEXT NOT NULL,
        PRIMARY KEY(citekey, sha256),
        FOREIGN KEY(citekey) REFERENCES legacy_reference_records(citekey)
    )
    """,
    """
    CREATE TABLE legacy_review_memberships (
        collection_id TEXT NOT NULL,
        citekey TEXT NOT NULL,
        status TEXT NOT NULL,
        decision_note TEXT,
        PRIMARY KEY(collection_id, citekey)
    )
    """,
    """
    CREATE TABLE legacy_abstracts (
        citekey TEXT NOT NULL,
        provider TEXT NOT NULL,
        source_url TEXT NOT NULL,
        retrieved_at TEXT NOT NULL,
        language TEXT,
        content_hash TEXT NOT NULL,
        text TEXT NOT NULL,
        PRIMARY KEY(citekey, provider, content_hash)
    )
    """,
    """
    CREATE TABLE legacy_citation_candidates (
        candidate_id TEXT PRIMARY KEY,
        proposed_citekey TEXT,
        title TEXT,
        authors TEXT,
        year TEXT,
        doi TEXT,
        metadata_status TEXT NOT NULL,
        abstract_status TEXT NOT NULL,
        abstract TEXT
    )
    """,
    """
    CREATE TABLE legacy_citation_edges (
        source_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        relation TEXT NOT NULL,
        source_locator TEXT NOT NULL,
        verification_status TEXT NOT NULL,
        PRIMARY KEY(source_id, target_id, relation, source_locator)
    )
    """,
    """
    CREATE TABLE citation_source_observations (
        source_observation_id TEXT PRIMARY KEY,
        record_schema_version INTEGER NOT NULL CHECK(
            record_schema_version = 1
        ),
        authority_kind TEXT NOT NULL CHECK(
            authority_kind = 'citation-source-observation'
        ),
        source_id TEXT NOT NULL,
        asserted_source_revision TEXT,
        source_path TEXT NOT NULL,
        source_sha256 TEXT NOT NULL,
        source_byte_size INTEGER NOT NULL CHECK(
            typeof(source_byte_size) = 'integer'
            AND source_byte_size > 0
        ),
        source_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE citation_candidates (
        candidate_id TEXT PRIMARY KEY,
        record_schema_version INTEGER NOT NULL CHECK(
            record_schema_version = 1
        ),
        authority_kind TEXT NOT NULL CHECK(
            authority_kind = 'citation-discovery-candidate'
        ),
        lifecycle_status TEXT NOT NULL CHECK(
            lifecycle_status = 'unaccepted-candidate'
        ),
        proposal_status TEXT NOT NULL CHECK(
            proposal_status = 'unaccepted-normalized-proposal'
        ),
        source_observation_id TEXT NOT NULL,
        source_locator TEXT NOT NULL,
        verbatim_entry TEXT,
        verbatim_identifier TEXT,
        verbatim_title TEXT,
        verbatim_authors TEXT,
        proposed_citekey TEXT,
        proposed_container_or_type TEXT,
        proposed_title TEXT,
        proposed_authors_json TEXT NOT NULL,
        proposed_year TEXT,
        proposed_doi TEXT,
        candidate_json TEXT NOT NULL,
        UNIQUE(source_observation_id, source_locator),
        FOREIGN KEY(source_observation_id)
            REFERENCES citation_source_observations(source_observation_id)
    )
    """,
    """
    CREATE TABLE citation_edges (
        edge_id TEXT PRIMARY KEY,
        record_schema_version INTEGER NOT NULL CHECK(
            record_schema_version = 1
        ),
        authority_kind TEXT NOT NULL CHECK(
            authority_kind = 'direct-citation-observation'
        ),
        evidence_status TEXT NOT NULL CHECK(
            evidence_status = 'source-observed-only'
        ),
        source_observation_id TEXT NOT NULL,
        target_candidate_id TEXT NOT NULL UNIQUE,
        relation TEXT NOT NULL CHECK(relation = 'cites'),
        source_locator TEXT NOT NULL,
        edge_json TEXT NOT NULL,
        FOREIGN KEY(source_observation_id)
            REFERENCES citation_source_observations(source_observation_id),
        FOREIGN KEY(target_candidate_id)
            REFERENCES citation_candidates(candidate_id)
    )
    """,
)

_V1_TABLE_MAP = (
    ("reference_records", "legacy_reference_records"),
    ("reference_aliases", "legacy_reference_aliases"),
    ("bibliography_occurrences", "legacy_bibliography_occurrences"),
    ("source_assets", "legacy_source_assets"),
    ("review_memberships", "legacy_review_memberships"),
    ("abstracts", "legacy_abstracts"),
    ("citation_candidates", "legacy_citation_candidates"),
    ("citation_edges", "legacy_citation_edges"),
)

_PUBLISHED_V2_TABLE_MAP = (
    ("legacy_reference_records", "legacy_reference_records"),
    ("legacy_reference_aliases", "legacy_reference_aliases"),
    (
        "legacy_bibliography_occurrences",
        "legacy_bibliography_occurrences",
    ),
    ("legacy_source_assets", "legacy_source_assets"),
    ("legacy_review_memberships", "legacy_review_memberships"),
    ("legacy_abstracts", "legacy_abstracts"),
    ("citation_candidates", "legacy_citation_candidates"),
    ("citation_edges", "legacy_citation_edges"),
)

_LEGACY_DROP_ORDER = (
    "citation_edges",
    "citation_candidates",
    "citation_source_observations",
    "legacy_citation_edges",
    "legacy_citation_candidates",
    "legacy_review_memberships",
    "legacy_abstracts",
    "legacy_source_assets",
    "legacy_bibliography_occurrences",
    "legacy_reference_aliases",
    "legacy_reference_records",
    "abstracts",
    "review_memberships",
    "source_assets",
    "bibliography_occurrences",
    "reference_aliases",
    "reference_records",
    "candidate_source_assets",
    "candidate_source_observations",
    "reference_candidates",
    "source_bibliography_observations",
    "catalog_metadata",
)


class CatalogError(ValueError):
    """Base class for fail-closed catalog operations."""


class CatalogSchemaError(CatalogError):
    """Raised when the catalog schema or metadata is incompatible."""


class CatalogMigrationRequired(CatalogSchemaError):
    """Raised when an exact known legacy schema needs explicit migration."""


class CatalogConflictError(CatalogError):
    """Raised when a write would replace differing catalog evidence."""


class CandidateConflictError(CatalogConflictError):
    """Raised instead of silently replacing candidate evidence."""


@dataclass(frozen=True)
class CatalogSchemaInfo:
    schema_version: int
    schema_fingerprint: str
    authority_boundary: str = _AUTHORITY_BOUNDARY


@dataclass(frozen=True)
class CatalogMigrationPlan:
    source_schema_version: int
    source_schema_fingerprint: str
    source_kind: str
    target_schema_version: int
    target_schema_fingerprint: str
    backup_required: bool = True
    authority_effect: str = "preserve-legacy-without-authority-upgrade"


@dataclass(frozen=True)
class _SchemaState:
    version: int
    fingerprint: str
    kind: str
    metadata: tuple[tuple[str, str], ...]


def _normalize_schema_sql(value: str | None) -> str | None:
    return None if value is None else " ".join(value.split())


def _schema_fingerprint(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_schema
        WHERE name NOT LIKE 'sqlite_%'
        ORDER BY type, name, tbl_name
        """
    ).fetchall()
    payload = tuple(
        {
            "type": str(row[0]),
            "name": str(row[1]),
            "table": str(row[2]),
            "sql": _normalize_schema_sql(row[3]),
        }
        for row in rows
    )
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "catalog-schema:sha256:" + hashlib.sha256(canonical).hexdigest()


def _target_schema_fingerprint() -> str:
    connection = sqlite3.connect(":memory:")
    try:
        for statement in _TARGET_SCHEMA_STATEMENTS:
            connection.execute(statement)
        return _schema_fingerprint(connection)
    finally:
        connection.close()


CATALOG_SCHEMA_FINGERPRINT = _target_schema_fingerprint()

_KNOWN_LEGACY_SCHEMAS = {
    _PROTOTYPE_V1_FINGERPRINT: "prototype-v1",
    _IDENTITY_V1_FINGERPRINT: "identity-v1",
    _PUBLISHED_V2_FINGERPRINT: "published-v2",
}


def _compact_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _observation_values(
    observation: SourceBibliographyObservation,
) -> tuple[object, ...]:
    return (
        observation.observation_id,
        observation.schema_version,
        observation.authority_kind,
        observation.source_id,
        observation.asserted_source_revision,
        observation.source_path,
        observation.bibliography_sha256,
        observation.bibliography_byte_size,
        observation.entry_index,
        observation.observed_citekey,
        observation.verbatim_entry,
        observation.parser.name,
        observation.parser.version,
        observation.to_json(),
    )


def _candidate_values(candidate: ReferenceCandidate) -> tuple[object, ...]:
    return (
        candidate.candidate_id,
        candidate.schema_version,
        candidate.authority_kind,
        candidate.lifecycle_status,
        candidate.proposed_citekey,
        candidate.citekey_status,
        candidate.entry_type,
        candidate.title,
        _compact_json(candidate.authors),
        candidate.year,
        candidate.doi,
        candidate.isbn,
        candidate.url,
        candidate.eprint,
        candidate.generator.name,
        candidate.generator.version,
        candidate.to_json(),
    )


def _graph_source_values(
    source: CitationSourceObservation,
) -> tuple[object, ...]:
    return (
        source.source_observation_id,
        source.schema_version,
        source.authority_kind,
        source.source_id,
        source.asserted_source_revision,
        source.source_path,
        source.source_sha256,
        source.source_byte_size,
        source.to_json(),
    )


def _graph_candidate_values(
    candidate: CitationCandidate,
) -> tuple[object, ...]:
    return (
        candidate.candidate_id,
        candidate.schema_version,
        candidate.authority_kind,
        candidate.lifecycle_status,
        candidate.proposal_status,
        candidate.source_observation_id,
        candidate.source_locator,
        candidate.verbatim_entry,
        candidate.verbatim_identifier,
        candidate.verbatim_title,
        candidate.verbatim_authors,
        candidate.proposed_citekey,
        candidate.proposed_container_or_type,
        candidate.proposed_title,
        _compact_json(candidate.proposed_authors),
        candidate.proposed_year,
        candidate.proposed_doi,
        candidate.to_json(),
    )


def _graph_edge_values(edge: CitationEdge) -> tuple[object, ...]:
    return (
        edge.edge_id,
        edge.schema_version,
        edge.authority_kind,
        edge.evidence_status,
        edge.source_observation_id,
        edge.target_candidate_id,
        edge.relation,
        edge.source_locator,
        edge.to_json(),
    )


def _asset_values(asset: SourceAssetRecord) -> tuple[object, ...]:
    return (
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
    )


_OBSERVATION_COLUMNS = (
    "observation_id",
    "record_schema_version",
    "authority_kind",
    "source_id",
    "asserted_source_revision",
    "source_path",
    "bibliography_sha256",
    "bibliography_byte_size",
    "entry_index",
    "observed_citekey",
    "verbatim_entry",
    "parser_name",
    "parser_version",
    "observation_json",
)

_CANDIDATE_COLUMNS = (
    "candidate_id",
    "record_schema_version",
    "authority_kind",
    "lifecycle_status",
    "proposed_citekey",
    "citekey_status",
    "entry_type",
    "title",
    "authors_json",
    "year",
    "doi",
    "isbn",
    "url",
    "eprint",
    "generator_name",
    "generator_version",
    "candidate_json",
)

_GRAPH_SOURCE_COLUMNS = (
    "source_observation_id",
    "record_schema_version",
    "authority_kind",
    "source_id",
    "asserted_source_revision",
    "source_path",
    "source_sha256",
    "source_byte_size",
    "source_json",
)

_GRAPH_CANDIDATE_COLUMNS = (
    "candidate_id",
    "record_schema_version",
    "authority_kind",
    "lifecycle_status",
    "proposal_status",
    "source_observation_id",
    "source_locator",
    "verbatim_entry",
    "verbatim_identifier",
    "verbatim_title",
    "verbatim_authors",
    "proposed_citekey",
    "proposed_container_or_type",
    "proposed_title",
    "proposed_authors_json",
    "proposed_year",
    "proposed_doi",
    "candidate_json",
)

_GRAPH_EDGE_COLUMNS = (
    "edge_id",
    "record_schema_version",
    "authority_kind",
    "evidence_status",
    "source_observation_id",
    "target_candidate_id",
    "relation",
    "source_locator",
    "edge_json",
)


class ReferenceCatalog:
    """SQLite working projection; immutable records remain authoritative."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> CatalogSchemaInfo:
        path = self._safe_path(create_parent=True)
        connection = self._open(path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            state = self._inspect_schema(connection)
            if state is None:
                self._create_target_schema(connection)
                self._write_target_metadata(connection)
                self._require_current_schema(connection)
            elif state.kind != "current":
                raise self._migration_required(state)
            else:
                self._require_current_schema(connection)
            connection.commit()
            return CatalogSchemaInfo(
                CATALOG_SCHEMA_VERSION,
                CATALOG_SCHEMA_FINGERPRINT,
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def schema_info(self) -> CatalogSchemaInfo:
        with self._read_transaction() as connection:
            self._require_current_schema(connection)
            return CatalogSchemaInfo(
                CATALOG_SCHEMA_VERSION,
                CATALOG_SCHEMA_FINGERPRINT,
            )

    def migration_plan(self) -> CatalogMigrationPlan | None:
        path = self._safe_path(create_parent=False)
        connection = self._open(path)
        try:
            state = self._inspect_schema(connection)
        finally:
            connection.close()
        if state is None:
            return None
        if state.kind == "current":
            return None
        if state.kind not in _KNOWN_LEGACY_SCHEMAS.values():
            raise CatalogSchemaError("catalog schema is not migratable")
        return CatalogMigrationPlan(
            source_schema_version=state.version,
            source_schema_fingerprint=state.fingerprint,
            source_kind=state.kind,
            target_schema_version=CATALOG_SCHEMA_VERSION,
            target_schema_fingerprint=CATALOG_SCHEMA_FINGERPRINT,
        )

    def migrate(self, *, backup_confirmed: bool = False) -> CatalogSchemaInfo:
        path = self._safe_path(create_parent=False)
        connection = self._open(path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            state = self._inspect_schema(connection)
            if state is None:
                raise CatalogSchemaError(
                    "empty catalog has no legacy schema to migrate; "
                    "use initialize()"
                )
            if state.kind == "current":
                self._require_current_schema(connection)
                connection.commit()
                return CatalogSchemaInfo(
                    CATALOG_SCHEMA_VERSION,
                    CATALOG_SCHEMA_FINGERPRINT,
                )
            if state.kind not in _KNOWN_LEGACY_SCHEMAS.values():
                raise CatalogSchemaError(
                    "catalog schema is not a repository-known migration source"
                )
            if backup_confirmed is not True:
                raise CatalogMigrationRequired(
                    "migration requires a verified external backup or "
                    "disposable working copy; retry with "
                    "backup_confirmed=True only after "
                    "that preflight"
                )
            snapshot = self._snapshot_legacy(connection, state)
            self._migration_checkpoint("snapshot-validated")
            for table in _LEGACY_DROP_ORDER:
                connection.execute(
                    f'DROP TABLE IF EXISTS "{table}"'  # noqa: S608
                )
            self._migration_checkpoint("legacy-schema-dropped")
            self._create_target_schema(connection)
            self._migration_checkpoint("target-schema-created")
            self._restore_snapshot(connection, snapshot)
            self._migration_checkpoint("rows-restored")
            self._write_target_metadata(connection)
            self._require_current_schema(connection)
            self._migration_checkpoint("target-verified")
            connection.commit()
            return CatalogSchemaInfo(
                CATALOG_SCHEMA_VERSION,
                CATALOG_SCHEMA_FINGERPRINT,
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def import_candidates(
        self,
        candidates: Iterable[ReferenceCandidate],
        observations: Iterable[SourceBibliographyObservation],
    ) -> None:
        """Append exact observations and candidates in one transaction."""
        candidate_values = tuple(candidates)
        observation_values = tuple(observations)
        if any(
            not isinstance(item, ReferenceCandidate)
            for item in candidate_values
        ):
            raise TypeError("candidates must contain ReferenceCandidate values")
        if any(
            not isinstance(item, SourceBibliographyObservation)
            for item in observation_values
        ):
            raise TypeError(
                "observations must contain SourceBibliographyObservation values"
            )
        with self._write_transaction() as connection:
            for observation in observation_values:
                self._insert_exact(
                    connection,
                    table="source_bibliography_observations",
                    columns=_OBSERVATION_COLUMNS,
                    values=_observation_values(observation),
                    key_columns=("observation_id",),
                    key_values=(observation.observation_id,),
                    label=f"observation {observation.observation_id}",
                    conflict_type=CandidateConflictError,
                )
            for candidate in candidate_values:
                self._insert_exact(
                    connection,
                    table="reference_candidates",
                    columns=_CANDIDATE_COLUMNS,
                    values=_candidate_values(candidate),
                    key_columns=("candidate_id",),
                    key_values=(candidate.candidate_id,),
                    label=f"candidate {candidate.candidate_id}",
                    conflict_type=CandidateConflictError,
                )
                for observation_id in candidate.source_observation_ids:
                    self._insert_exact(
                        connection,
                        table="candidate_source_observations",
                        columns=("candidate_id", "observation_id"),
                        values=(candidate.candidate_id, observation_id),
                        key_columns=("candidate_id", "observation_id"),
                        key_values=(candidate.candidate_id, observation_id),
                        label=(
                            f"candidate observation {candidate.candidate_id} / "
                            f"{observation_id}"
                        ),
                        conflict_type=CandidateConflictError,
                    )
            self._validate_identity_rows(connection)

    def read_observations(self) -> tuple[SourceBibliographyObservation, ...]:
        with self._read_transaction() as connection:
            self._require_current_schema(connection)
            return self._read_observations(connection)

    def read_candidates(self) -> tuple[ReferenceCandidate, ...]:
        with self._read_transaction() as connection:
            self._require_current_schema(connection)
            observations = {
                item.observation_id
                for item in self._read_observations(connection)
            }
            return self._read_candidates(connection, observations)

    def export_identity_json(self) -> str:
        """Return a deterministic disposable projection of identity records."""
        with self._read_transaction() as connection:
            self._require_current_schema(connection)
            observations = self._read_observations(connection)
            observation_ids = {item.observation_id for item in observations}
            candidates = self._read_candidates(connection, observation_ids)
        payload = {
            "authority_boundary": _AUTHORITY_BOUNDARY,
            "schema_version": CATALOG_SCHEMA_VERSION,
            "schema_fingerprint": CATALOG_SCHEMA_FINGERPRINT,
            "observations": [
                json.loads(item.to_json()) for item in observations
            ],
            "candidates": [json.loads(item.to_json()) for item in candidates],
        }
        return (
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    def record_source_asset(self, asset: SourceAssetRecord) -> None:
        self.record_source_assets((asset,))

    def record_source_assets(self, assets: Iterable[SourceAssetRecord]) -> None:
        asset_values = tuple(assets)
        if any(
            not isinstance(item, SourceAssetRecord) for item in asset_values
        ):
            raise TypeError("assets must contain SourceAssetRecord values")
        columns = (
            "candidate_id",
            "proposed_citekey",
            "identity_status",
            "citekey_status",
            "sha256",
            "byte_size",
            "root_alias",
            "relative_path",
            "rights_status",
            "asset_status",
        )
        with self._write_transaction() as connection:
            for asset in asset_values:
                values = _asset_values(asset)
                self._insert_exact(
                    connection,
                    table="candidate_source_assets",
                    columns=columns,
                    values=values,
                    key_columns=("candidate_id", "sha256"),
                    key_values=(asset.candidate_id, asset.sha256),
                    label=f"source asset {asset.candidate_id} / {asset.sha256}",
                )

    def set_review_membership(self, membership: ReviewMembership) -> None:
        self.set_review_memberships((membership,))

    def set_review_memberships(
        self, memberships: Iterable[ReviewMembership]
    ) -> None:
        """Append identical legacy rows; review redesign remains deferred."""
        values = tuple(memberships)
        if any(not isinstance(item, ReviewMembership) for item in values):
            raise TypeError("memberships must contain ReviewMembership values")
        columns = ("collection_id", "citekey", "status", "decision_note")
        with self._write_transaction() as connection:
            for membership in values:
                row = (
                    membership.collection_id,
                    membership.citekey,
                    membership.status.value,
                    membership.decision_note,
                )
                self._insert_exact(
                    connection,
                    table="legacy_review_memberships",
                    columns=columns,
                    values=row,
                    key_columns=("collection_id", "citekey"),
                    key_values=(membership.collection_id, membership.citekey),
                    label=(
                        "legacy review membership "
                        f"{membership.collection_id} / {membership.citekey}"
                    ),
                )

    def import_citation_graph(self, graph: CitationGraph) -> None:
        """Append one fully validated graph batch in a single transaction."""
        if not isinstance(graph, CitationGraph):
            raise TypeError("graph must be a CitationGraph value")
        # Revalidate even frozen caller data at the catalog trust boundary.
        graph = CitationGraph.create(
            sources=graph.sources,
            candidates=graph.candidates,
            edges=graph.edges,
        )
        with self._write_transaction() as connection:
            for source in graph.sources:
                self._insert_exact(
                    connection,
                    table="citation_source_observations",
                    columns=_GRAPH_SOURCE_COLUMNS,
                    values=_graph_source_values(source),
                    key_columns=("source_observation_id",),
                    key_values=(source.source_observation_id,),
                    label=(
                        "citation source observation "
                        f"{source.source_observation_id}"
                    ),
                )
            for candidate in graph.candidates:
                self._insert_exact(
                    connection,
                    table="citation_candidates",
                    columns=_GRAPH_CANDIDATE_COLUMNS,
                    values=_graph_candidate_values(candidate),
                    key_columns=("candidate_id",),
                    key_values=(candidate.candidate_id,),
                    label=f"citation candidate {candidate.candidate_id}",
                )
            for edge in graph.edges:
                self._insert_exact(
                    connection,
                    table="citation_edges",
                    columns=_GRAPH_EDGE_COLUMNS,
                    values=_graph_edge_values(edge),
                    key_columns=("edge_id",),
                    key_values=(edge.edge_id,),
                    label=f"citation edge {edge.edge_id}",
                )
            self._validate_graph_rows(connection)

    def read_citation_graph(self) -> CitationGraph:
        with self._read_transaction() as connection:
            self._require_current_schema(connection)
            return self._read_citation_graph(connection)

    def export_citation_graph_json(self) -> str:
        return self.read_citation_graph().to_json()

    def add_abstract(self, abstract: AbstractRecord) -> None:
        columns = (
            "citekey",
            "provider",
            "source_url",
            "retrieved_at",
            "language",
            "content_hash",
            "text",
        )
        values = (
            abstract.citekey,
            abstract.provider,
            abstract.source_url,
            abstract.retrieved_at,
            abstract.language,
            abstract.content_hash,
            abstract.text,
        )
        with self._write_transaction() as connection:
            self._insert_exact(
                connection,
                table="legacy_abstracts",
                columns=columns,
                values=values,
                key_columns=("citekey", "provider", "content_hash"),
                key_values=(
                    abstract.citekey,
                    abstract.provider,
                    abstract.content_hash,
                ),
                label="legacy abstract",
            )

    def counts(self) -> dict[str, int]:
        projections = (
            ("candidate_records", "reference_candidates"),
            ("bibliography_observations", "source_bibliography_observations"),
            ("source_assets", "candidate_source_assets"),
            ("legacy_reference_rows", "legacy_reference_records"),
            ("unprovenanced_alias_rows", "legacy_reference_aliases"),
            ("review_memberships", "legacy_review_memberships"),
            ("abstracts", "legacy_abstracts"),
            (
                "citation_source_observations",
                "citation_source_observations",
            ),
            ("citation_candidates", "citation_candidates"),
            ("citation_edges", "citation_edges"),
            ("legacy_citation_candidates", "legacy_citation_candidates"),
            ("legacy_citation_edges", "legacy_citation_edges"),
        )
        with self._read_transaction() as connection:
            self._require_current_schema(connection)
            return {
                label: int(
                    connection.execute(
                        f'SELECT COUNT(*) FROM "{table}"'  # noqa: S608
                    ).fetchone()[0]
                )
                for label, table in projections
            }

    @contextmanager
    def _read_transaction(self) -> Iterator[sqlite3.Connection]:
        path = self._safe_path(create_parent=False)
        connection = self._open(path)
        try:
            connection.execute("BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def _write_transaction(self) -> Iterator[sqlite3.Connection]:
        path = self._safe_path(create_parent=False)
        connection = self._open(path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._require_current_schema(connection)
            yield connection
            self._require_foreign_keys(connection)
            self._validate_identity_rows(connection)
            self._validate_graph_rows(connection)
            connection.commit()
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise CatalogConflictError(
                f"catalog write violates schema integrity: {error}"
            ) from error
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _open(path: Path) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(path, isolation_level=None)
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            return connection
        except sqlite3.DatabaseError as error:
            raise CatalogSchemaError(
                "catalog is not a readable SQLite database; preserve it and "
                "restore or migrate from a verified backup"
            ) from error

    def _inspect_schema(
        self, connection: sqlite3.Connection
    ) -> _SchemaState | None:
        try:
            objects = connection.execute(
                """
                SELECT name FROM sqlite_schema
                WHERE name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        except sqlite3.DatabaseError as error:
            raise CatalogSchemaError(
                "catalog schema cannot be inspected; preserve it and use a "
                "verified backup or explicit migration"
            ) from error
        if not objects:
            return None
        fingerprint = _schema_fingerprint(connection)
        try:
            metadata_rows = connection.execute(
                "SELECT key, value FROM catalog_metadata ORDER BY key"
            ).fetchall()
        except sqlite3.DatabaseError as error:
            raise CatalogSchemaError(
                "catalog metadata is missing or incompatible; preserve the "
                "database and use a verified backup or explicit migration"
            ) from error
        metadata = tuple((str(row[0]), str(row[1])) for row in metadata_rows)
        metadata_map = dict(metadata)
        if len(metadata_map) != len(metadata):
            raise CatalogSchemaError("catalog metadata contains duplicate keys")
        raw_version = metadata_map.get("schema_version")
        try:
            version = int(raw_version) if raw_version is not None else -1
        except ValueError as error:
            raise CatalogSchemaError(
                "catalog schema_version metadata is not an integer"
            ) from error
        if raw_version != str(version):
            raise CatalogSchemaError(
                "catalog schema_version metadata is not canonical"
            )
        if version > CATALOG_SCHEMA_VERSION:
            raise CatalogSchemaError(
                f"catalog schema version {version} is newer than supported "
                f"version {CATALOG_SCHEMA_VERSION}; use a compatible build"
            )
        if version == CATALOG_SCHEMA_VERSION:
            if frozenset(metadata_map) != _SCHEMA_METADATA_KEYS:
                raise CatalogSchemaError(
                    "current catalog metadata keys are incomplete or unexpected"
                )
            stored = metadata_map["schema_fingerprint"]
            if stored != CATALOG_SCHEMA_FINGERPRINT:
                raise CatalogSchemaError(
                    "catalog schema fingerprint metadata differs from the "
                    "supported fingerprint; preserve the database and require "
                    "an explicit migration or recovery"
                )
            if fingerprint != CATALOG_SCHEMA_FINGERPRINT:
                raise CatalogSchemaError(
                    "catalog actual schema differs from its recorded supported "
                    "schema; preserve the database and require an explicit "
                    "migration or recovery"
                )
            return _SchemaState(version, fingerprint, "current", metadata)
        if version in {1, 2}:
            expected_keys = (
                _LEGACY_METADATA_KEYS if version == 1 else _SCHEMA_METADATA_KEYS
            )
            if frozenset(metadata_map) != expected_keys:
                raise CatalogSchemaError(
                    f"version {version} catalog metadata is incomplete or "
                    "unexpected"
                )
            if version == 2 and (
                metadata_map["schema_fingerprint"] != fingerprint
            ):
                raise CatalogSchemaError(
                    "version 2 catalog fingerprint metadata differs from its "
                    "actual schema; preserve it and require explicit recovery"
                )
            kind = _KNOWN_LEGACY_SCHEMAS.get(fingerprint)
            if kind is None:
                raise CatalogSchemaError(
                    f"catalog claims schema version {version} but its actual "
                    "schema is unknown or altered; preserve it and require an "
                    "explicit reviewed migration"
                )
            self._require_foreign_keys(connection)
            return _SchemaState(version, fingerprint, kind, metadata)
        raise CatalogSchemaError(
            f"catalog schema version {version} is unsupported; preserve the "
            "database and require an explicit reviewed migration"
        )

    def _require_current_schema(self, connection: sqlite3.Connection) -> None:
        state = self._inspect_schema(connection)
        if state is None:
            raise CatalogSchemaError("catalog is empty; initialize it first")
        if state.kind != "current":
            raise self._migration_required(state)
        self._require_foreign_keys(connection)
        self._validate_identity_rows(connection)
        self._validate_graph_rows(connection)

    @staticmethod
    def _migration_required(state: _SchemaState) -> CatalogMigrationRequired:
        return CatalogMigrationRequired(
            f"recognized {state.kind} catalog ({state.fingerprint}) requires "
            f"forward migration to schema version {CATALOG_SCHEMA_VERSION}; "
            "create and verify an "
            "external backup or disposable copy, then call "
            "migrate(backup_confirmed=True)"
        )

    @staticmethod
    def _require_foreign_keys(connection: sqlite3.Connection) -> None:
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            first = tuple(violations[0])
            raise CatalogSchemaError(
                "catalog foreign-key integrity check failed; first violation "
                f"is {first!r}"
            )

    @staticmethod
    def _create_target_schema(connection: sqlite3.Connection) -> None:
        for statement in _TARGET_SCHEMA_STATEMENTS:
            connection.execute(statement)
        actual = _schema_fingerprint(connection)
        if actual != CATALOG_SCHEMA_FINGERPRINT:
            raise CatalogSchemaError(
                "created catalog schema fingerprint is not the supported "
                "fingerprint"
            )

    @staticmethod
    def _write_target_metadata(connection: sqlite3.Connection) -> None:
        connection.execute(
            "INSERT INTO catalog_metadata(key, value) VALUES (?, ?)",
            ("schema_version", str(CATALOG_SCHEMA_VERSION)),
        )
        connection.execute(
            "INSERT INTO catalog_metadata(key, value) VALUES (?, ?)",
            ("schema_fingerprint", CATALOG_SCHEMA_FINGERPRINT),
        )

    @staticmethod
    def _insert_exact(
        connection: sqlite3.Connection,
        *,
        table: str,
        columns: tuple[str, ...],
        values: tuple[object, ...],
        key_columns: tuple[str, ...],
        key_values: tuple[object, ...],
        label: str,
        conflict_type: type[CatalogConflictError] = CatalogConflictError,
    ) -> bool:
        select_columns = ", ".join(f'"{item}"' for item in columns)
        where = " AND ".join(f'"{item}" = ?' for item in key_columns)
        existing = connection.execute(
            f'SELECT {select_columns} FROM "{table}" WHERE {where}',  # noqa: S608
            key_values,
        ).fetchone()
        if existing is not None:
            if tuple(existing) == values:
                return False
            raise conflict_type(f"{label} conflicts with existing evidence")
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(f'"{item}"' for item in columns)
        connection.execute(
            f'INSERT INTO "{table}" ({column_sql}) '  # noqa: S608
            f"VALUES ({placeholders})",
            values,
        )
        return True

    def _read_observations(
        self, connection: sqlite3.Connection
    ) -> tuple[SourceBibliographyObservation, ...]:
        rows = connection.execute(
            """
            SELECT observation_id, record_schema_version, authority_kind,
                   source_id, asserted_source_revision, source_path,
                   bibliography_sha256, bibliography_byte_size, entry_index,
                   observed_citekey, verbatim_entry, parser_name,
                   parser_version, observation_json
            FROM source_bibliography_observations
            ORDER BY observation_id
            """
        ).fetchall()
        result: list[SourceBibliographyObservation] = []
        for row in rows:
            try:
                observation = SourceBibliographyObservation.from_json(
                    str(row[13])
                )
            except ValueError as error:
                raise CatalogSchemaError(
                    f"observation row {row[0]} has invalid canonical JSON"
                ) from error
            if tuple(row) != _observation_values(observation):
                raise CatalogSchemaError(
                    f"observation row {row[0]} differs from its canonical JSON"
                )
            result.append(observation)
        return tuple(result)

    def _read_candidates(
        self,
        connection: sqlite3.Connection,
        observation_ids: set[str],
    ) -> tuple[ReferenceCandidate, ...]:
        rows = connection.execute(
            """
            SELECT candidate_id, record_schema_version, authority_kind,
                   lifecycle_status, proposed_citekey, citekey_status,
                   entry_type, title, authors_json, year, doi, isbn, url,
                   eprint, generator_name, generator_version, candidate_json
            FROM reference_candidates
            ORDER BY candidate_id
            """
        ).fetchall()
        result: list[ReferenceCandidate] = []
        for row in rows:
            try:
                candidate = ReferenceCandidate.from_json(str(row[16]))
            except ValueError as error:
                raise CatalogSchemaError(
                    f"candidate row {row[0]} has invalid canonical JSON"
                ) from error
            if tuple(row) != _candidate_values(candidate):
                raise CatalogSchemaError(
                    f"candidate row {row[0]} differs from its canonical JSON"
                )
            linked = tuple(
                str(item[0])
                for item in connection.execute(
                    """
                    SELECT observation_id
                    FROM candidate_source_observations
                    WHERE candidate_id = ?
                    ORDER BY observation_id
                    """,
                    (candidate.candidate_id,),
                ).fetchall()
            )
            if linked != candidate.source_observation_ids:
                raise CatalogSchemaError(
                    f"candidate {candidate.candidate_id} source links differ "
                    "from canonical JSON"
                )
            if not set(linked) <= observation_ids:
                raise CatalogSchemaError(
                    f"candidate {candidate.candidate_id} links missing "
                    "observations"
                )
            result.append(candidate)
        return tuple(result)

    def _read_citation_graph(
        self, connection: sqlite3.Connection
    ) -> CitationGraph:
        source_rows = connection.execute(
            """
            SELECT source_observation_id, record_schema_version,
                   authority_kind, source_id, asserted_source_revision,
                   source_path, source_sha256, source_byte_size, source_json
            FROM citation_source_observations
            ORDER BY source_observation_id
            """
        ).fetchall()
        sources: list[CitationSourceObservation] = []
        for row in source_rows:
            try:
                source = CitationSourceObservation.from_json(str(row[8]))
            except CitationGraphError as error:
                raise CatalogSchemaError(
                    f"citation source row {row[0]} has invalid canonical JSON"
                ) from error
            if tuple(row) != _graph_source_values(source):
                raise CatalogSchemaError(
                    f"citation source row {row[0]} differs from canonical JSON"
                )
            sources.append(source)

        candidate_rows = connection.execute(
            """
            SELECT candidate_id, record_schema_version, authority_kind,
                   lifecycle_status, proposal_status, source_observation_id,
                   source_locator, verbatim_entry, verbatim_identifier,
                   verbatim_title, verbatim_authors, proposed_citekey,
                   proposed_container_or_type, proposed_title,
                   proposed_authors_json,
                   proposed_year, proposed_doi, candidate_json
            FROM citation_candidates
            ORDER BY candidate_id
            """
        ).fetchall()
        candidates: list[CitationCandidate] = []
        for row in candidate_rows:
            try:
                candidate = CitationCandidate.from_json(str(row[17]))
            except CitationGraphError as error:
                raise CatalogSchemaError(
                    f"citation candidate row {row[0]} has invalid "
                    "canonical JSON"
                ) from error
            if tuple(row) != _graph_candidate_values(candidate):
                raise CatalogSchemaError(
                    f"citation candidate row {row[0]} differs from canonical "
                    "JSON"
                )
            candidates.append(candidate)

        edge_rows = connection.execute(
            """
            SELECT edge_id, record_schema_version, authority_kind,
                   evidence_status, source_observation_id,
                   target_candidate_id, relation, source_locator, edge_json
            FROM citation_edges
            ORDER BY edge_id
            """
        ).fetchall()
        edges: list[CitationEdge] = []
        for row in edge_rows:
            try:
                edge = CitationEdge.from_json(str(row[8]))
            except CitationGraphError as error:
                raise CatalogSchemaError(
                    f"citation edge row {row[0]} has invalid canonical JSON"
                ) from error
            if tuple(row) != _graph_edge_values(edge):
                raise CatalogSchemaError(
                    f"citation edge row {row[0]} differs from canonical JSON"
                )
            edges.append(edge)
        try:
            return CitationGraph.create(
                sources=tuple(sources),
                candidates=tuple(candidates),
                edges=tuple(edges),
            )
        except CitationGraphError as error:
            raise CatalogSchemaError(
                f"catalog citation graph violates graph integrity: {error}"
            ) from error

    def _validate_graph_rows(self, connection: sqlite3.Connection) -> None:
        self._read_citation_graph(connection)

    @staticmethod
    def _source_asset_from_row(
        row: tuple[object, ...], *, label: str
    ) -> SourceAssetRecord:
        raw_byte_size = row[5]
        if isinstance(raw_byte_size, bool) or not isinstance(
            raw_byte_size, int
        ):
            raise CatalogSchemaError(
                f"{label} byte_size is not stored as an integer"
            )
        try:
            asset = SourceAssetRecord(
                candidate_id=str(row[0]),
                proposed_citekey=str(row[1]),
                identity_status=str(row[2]),
                citekey_status=str(row[3]),
                sha256=str(row[4]),
                byte_size=raw_byte_size,
                root_alias=str(row[6]),
                relative_path=str(row[7]),
                rights_status=str(row[8]),
                asset_status=str(row[9]),
            )
        except (TypeError, ValueError) as error:
            raise CatalogSchemaError(f"{label} is malformed") from error
        if tuple(row) != _asset_values(asset):
            raise CatalogSchemaError(
                f"{label} contains lossy or unsupported storage types"
            )
        return asset

    @staticmethod
    def _require_asset_candidate_match(
        asset: SourceAssetRecord,
        candidate_by_id: dict[str, ReferenceCandidate],
        *,
        label: str,
    ) -> None:
        candidate = candidate_by_id.get(asset.candidate_id)
        if candidate is None:
            raise CatalogSchemaError(f"{label} has no candidate identity")
        if (
            asset.proposed_citekey != candidate.proposed_citekey
            or asset.identity_status != candidate.lifecycle_status
            or asset.citekey_status != candidate.citekey_status
        ):
            raise CatalogSchemaError(f"{label} differs from candidate identity")

    def _validate_identity_rows(self, connection: sqlite3.Connection) -> None:
        observations = self._read_observations(connection)
        observation_ids = {item.observation_id for item in observations}
        candidates = self._read_candidates(connection, observation_ids)
        candidate_by_id = {item.candidate_id: item for item in candidates}
        asset_rows = connection.execute(
            """
            SELECT candidate_id, proposed_citekey, identity_status,
                   citekey_status, sha256, byte_size, root_alias,
                   relative_path, rights_status, asset_status
            FROM candidate_source_assets
            ORDER BY candidate_id, sha256
            """
        ).fetchall()
        for row in asset_rows:
            asset = self._source_asset_from_row(
                tuple(row), label="candidate source asset"
            )
            self._require_asset_candidate_match(
                asset,
                candidate_by_id,
                label="candidate source asset",
            )

    @staticmethod
    def _snapshot_table(
        connection: sqlite3.Connection, table: str
    ) -> tuple[tuple[str, ...], tuple[tuple[object, ...], ...]]:
        columns = tuple(
            str(row[1])
            for row in connection.execute(
                f'PRAGMA table_info("{table}")'  # noqa: S608
            ).fetchall()
        )
        column_sql = ", ".join(f'"{item}"' for item in columns)
        rows = tuple(
            tuple(row)
            for row in connection.execute(
                f'SELECT {column_sql} FROM "{table}" ORDER BY rowid'  # noqa: S608
            ).fetchall()
        )
        return columns, rows

    def _snapshot_legacy(
        self, connection: sqlite3.Connection, state: _SchemaState
    ) -> dict[str, Any]:
        table_map = (
            _PUBLISHED_V2_TABLE_MAP
            if state.kind == "published-v2"
            else _V1_TABLE_MAP
        )
        snapshot: dict[str, Any] = {
            "table_map": table_map,
            **{
                source: self._snapshot_table(connection, source)
                for source, _ in table_map
            },
        }
        if state.kind == "identity-v1":
            try:
                observations = tuple(
                    SourceBibliographyObservation.from_json(str(row[3]))
                    for row in connection.execute(
                        """
                        SELECT observation_id, authority_kind, observed_citekey,
                               observation_json
                        FROM source_bibliography_observations
                        ORDER BY observation_id
                        """
                    ).fetchall()
                )
            except ValueError as error:
                raise CatalogSchemaError(
                    "legacy observation canonical JSON is invalid"
                ) from error
            old_observation_rows = connection.execute(
                """
                SELECT observation_id, authority_kind, observed_citekey,
                       observation_json
                FROM source_bibliography_observations
                ORDER BY observation_id
                """
            ).fetchall()
            for row, observation in zip(
                old_observation_rows, observations, strict=True
            ):
                observation_expected = (
                    observation.observation_id,
                    observation.authority_kind,
                    observation.observed_citekey,
                    observation.to_json(),
                )
                if tuple(row) != observation_expected:
                    raise CatalogSchemaError(
                        "legacy observation scalar columns differ from "
                        "canonical JSON"
                    )
            try:
                candidates = tuple(
                    ReferenceCandidate.from_json(str(row[5]))
                    for row in connection.execute(
                        """
                        SELECT candidate_id, authority_kind, lifecycle_status,
                               proposed_citekey, citekey_status, candidate_json
                        FROM reference_candidates
                        ORDER BY candidate_id
                        """
                    ).fetchall()
                )
            except ValueError as error:
                raise CatalogSchemaError(
                    "legacy candidate canonical JSON is invalid"
                ) from error
            old_candidate_rows = connection.execute(
                """
                SELECT candidate_id, authority_kind, lifecycle_status,
                       proposed_citekey, citekey_status, candidate_json
                FROM reference_candidates
                ORDER BY candidate_id
                """
            ).fetchall()
            for row, candidate in zip(
                old_candidate_rows, candidates, strict=True
            ):
                candidate_expected = (
                    candidate.candidate_id,
                    candidate.authority_kind,
                    candidate.lifecycle_status,
                    candidate.proposed_citekey,
                    candidate.citekey_status,
                    candidate.to_json(),
                )
                if tuple(row) != candidate_expected:
                    raise CatalogSchemaError(
                        "legacy candidate scalar columns differ from "
                        "canonical JSON"
                    )
            links = self._snapshot_table(
                connection, "candidate_source_observations"
            )
            assets = self._snapshot_table(connection, "candidate_source_assets")
            observation_ids = {item.observation_id for item in observations}
            candidate_ids = {item.candidate_id for item in candidates}
            linked_by_candidate: dict[str, list[str]] = {
                item: [] for item in candidate_ids
            }
            for candidate_id, observation_id in links[1]:
                candidate_text = str(candidate_id)
                observation_text = str(observation_id)
                if (
                    candidate_text not in candidate_ids
                    or observation_text not in observation_ids
                ):
                    raise CatalogSchemaError(
                        "legacy candidate-source link has a missing identity"
                    )
                linked_by_candidate[candidate_text].append(observation_text)
            for candidate in candidates:
                linked = tuple(
                    sorted(linked_by_candidate[candidate.candidate_id])
                )
                if linked != candidate.source_observation_ids:
                    raise CatalogSchemaError(
                        "legacy candidate-source links differ from canonical "
                        "JSON"
                    )
            candidate_by_id = {
                candidate.candidate_id: candidate for candidate in candidates
            }
            for row in assets[1]:
                asset = self._source_asset_from_row(
                    row, label="legacy candidate source asset"
                )
                self._require_asset_candidate_match(
                    asset,
                    candidate_by_id,
                    label="legacy candidate source asset",
                )
            snapshot.update(
                {
                    "observations": observations,
                    "candidates": candidates,
                    "candidate_source_observations": links,
                    "candidate_source_assets": assets,
                }
            )
        elif state.kind == "published-v2":
            self._validate_identity_rows(connection)
            observations = self._read_observations(connection)
            observation_ids = {
                observation.observation_id for observation in observations
            }
            candidates = self._read_candidates(connection, observation_ids)
            snapshot.update(
                {
                    "observations": observations,
                    "candidates": candidates,
                    "candidate_source_observations": self._snapshot_table(
                        connection,
                        "candidate_source_observations",
                    ),
                    "candidate_source_assets": self._snapshot_table(
                        connection,
                        "candidate_source_assets",
                    ),
                }
            )
        else:
            snapshot.update(
                {
                    "observations": (),
                    "candidates": (),
                    "candidate_source_observations": (
                        ("candidate_id", "observation_id"),
                        (),
                    ),
                    "candidate_source_assets": (
                        (
                            "candidate_id",
                            "proposed_citekey",
                            "identity_status",
                            "citekey_status",
                            "sha256",
                            "byte_size",
                            "root_alias",
                            "relative_path",
                            "rights_status",
                            "asset_status",
                        ),
                        (),
                    ),
                }
            )
        return snapshot

    def _restore_snapshot(
        self,
        connection: sqlite3.Connection,
        snapshot: dict[str, Any],
    ) -> None:
        for observation in snapshot["observations"]:
            self._insert_exact(
                connection,
                table="source_bibliography_observations",
                columns=_OBSERVATION_COLUMNS,
                values=_observation_values(observation),
                key_columns=("observation_id",),
                key_values=(observation.observation_id,),
                label="migrated observation",
            )
        for candidate in snapshot["candidates"]:
            self._insert_exact(
                connection,
                table="reference_candidates",
                columns=_CANDIDATE_COLUMNS,
                values=_candidate_values(candidate),
                key_columns=("candidate_id",),
                key_values=(candidate.candidate_id,),
                label="migrated candidate",
            )
        self._restore_table(
            connection,
            "candidate_source_observations",
            snapshot["candidate_source_observations"],
        )
        self._restore_table(
            connection,
            "candidate_source_assets",
            snapshot["candidate_source_assets"],
        )
        for source, target in snapshot["table_map"]:
            self._restore_table(connection, target, snapshot[source])
        self._validate_identity_rows(connection)

    @staticmethod
    def _restore_table(
        connection: sqlite3.Connection,
        table: str,
        snapshot: tuple[tuple[str, ...], tuple[tuple[object, ...], ...]],
    ) -> None:
        columns, rows = snapshot
        if not rows:
            return
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(f'"{item}"' for item in columns)
        connection.executemany(
            f'INSERT INTO "{table}" ({column_sql}) '  # noqa: S608
            f"VALUES ({placeholders})",
            rows,
        )

    def _migration_checkpoint(self, step: str) -> None:
        """Test seam proving DDL/data rollback; production is a no-op."""
        del step

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
        if state == "missing" and not create_parent:
            raise CatalogSchemaError(
                "catalog does not exist; initialize a new catalog explicitly"
            )
        return root.child_path(self.path.name)
