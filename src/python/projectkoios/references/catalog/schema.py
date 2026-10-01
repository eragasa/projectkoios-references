from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass

CATALOG_SCHEMA_VERSION = 5
SUPPORTED_CATALOG_SCHEMA_VERSIONS = (CATALOG_SCHEMA_VERSION,)

_SCHEMA_METADATA_KEYS = frozenset({"schema_version", "schema_fingerprint"})
_LEGACY_METADATA_KEYS = frozenset({"schema_version"})
_AUTHORITY_BOUNDARY = "non-authoritative-rebuildable-working-projection"
_MAX_STATE_PROJECTIONS = 4096
_MAX_STATE_PROJECTION_JSON_BYTES = 16_000_000
_MAX_STATE_PROJECTION_EXPORT_BYTES = 20_000_000

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
_PUBLISHED_V3_FINGERPRINT = (
    "catalog-schema:sha256:"
    "d2970cd39caff4971407ea11b9ab4ea630d53c0b11e1b0dd58a65f045c0bffaa"
)
_PUBLISHED_V4_FINGERPRINT = (
    "catalog-schema:sha256:"
    "30bb68e78832c461011f7e2a9ba7812c93aa099c866a84869a8415500f415e48"
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
    """
    CREATE TABLE technical_review_records (
        record_id TEXT PRIMARY KEY,
        record_schema_version INTEGER NOT NULL CHECK(
            record_schema_version = 1
        ),
        authority_kind TEXT NOT NULL CHECK(
            authority_kind = 'technical-review-observation'
        ),
        producer_name TEXT NOT NULL,
        producer_version TEXT NOT NULL,
        effective_limits_id TEXT NOT NULL,
        subject_id TEXT NOT NULL,
        context_id TEXT NOT NULL,
        technical_kind TEXT NOT NULL,
        outcome TEXT NOT NULL,
        transition_kind TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        actor_kind TEXT NOT NULL CHECK(actor_kind = 'processor'),
        authority_scope TEXT NOT NULL CHECK(
            authority_scope = 'technical-processor'
        ),
        authority_domain TEXT NOT NULL,
        verification_record_id TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        supersedes_record_id TEXT UNIQUE,
        record_json TEXT NOT NULL,
        FOREIGN KEY(supersedes_record_id)
            REFERENCES technical_review_records(record_id)
    )
    """,
    """
    CREATE TABLE human_review_decisions (
        decision_id TEXT PRIMARY KEY,
        record_schema_version INTEGER NOT NULL CHECK(
            record_schema_version = 1
        ),
        authority_kind TEXT NOT NULL CHECK(
            authority_kind = 'human-review-decision'
        ),
        producer_name TEXT NOT NULL,
        producer_version TEXT NOT NULL,
        effective_limits_id TEXT NOT NULL,
        subject_id TEXT NOT NULL,
        context_id TEXT NOT NULL,
        dimension TEXT NOT NULL,
        decision TEXT NOT NULL,
        transition_kind TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        actor_kind TEXT NOT NULL CHECK(actor_kind = 'person'),
        authority_scope TEXT NOT NULL,
        authority_domain TEXT NOT NULL,
        verification_record_id TEXT NOT NULL,
        decided_at TEXT NOT NULL,
        supersedes_decision_id TEXT UNIQUE,
        decision_json TEXT NOT NULL,
        FOREIGN KEY(supersedes_decision_id)
            REFERENCES human_review_decisions(decision_id)
    )
    """,
    """
    CREATE TABLE reference_state_projections (
        projection_id TEXT PRIMARY KEY,
        record_schema_version INTEGER NOT NULL CHECK(
            record_schema_version = 1
        ),
        artifact_kind TEXT NOT NULL CHECK(
            artifact_kind =
                'projectkoios.references.reference-state-projection'
        ),
        subject_id TEXT NOT NULL,
        authoritative_input_ids_json TEXT NOT NULL,
        projection_json TEXT NOT NULL,
        FOREIGN KEY(subject_id) REFERENCES reference_candidates(candidate_id)
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

_PUBLISHED_V3_TABLE_MAP = (
    ("legacy_reference_records", "legacy_reference_records"),
    ("legacy_reference_aliases", "legacy_reference_aliases"),
    (
        "legacy_bibliography_occurrences",
        "legacy_bibliography_occurrences",
    ),
    ("legacy_source_assets", "legacy_source_assets"),
    ("legacy_review_memberships", "legacy_review_memberships"),
    ("legacy_abstracts", "legacy_abstracts"),
    ("legacy_citation_candidates", "legacy_citation_candidates"),
    ("legacy_citation_edges", "legacy_citation_edges"),
    ("citation_source_observations", "citation_source_observations"),
    ("citation_candidates", "citation_candidates"),
    ("citation_edges", "citation_edges"),
)

_PUBLISHED_V4_TABLE_MAP = (
    *_PUBLISHED_V3_TABLE_MAP,
    ("technical_review_records", "technical_review_records"),
    ("human_review_decisions", "human_review_decisions"),
)

_LEGACY_DROP_ORDER = (
    "reference_state_projections",
    "human_review_decisions",
    "technical_review_records",
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
    _PUBLISHED_V3_FINGERPRINT: "published-v3",
    _PUBLISHED_V4_FINGERPRINT: "published-v4",
}
_LEGACY_SCHEMA_VERSIONS = {
    "prototype-v1": 1,
    "identity-v1": 1,
    "published-v2": 2,
    "published-v3": 3,
    "published-v4": 4,
}
