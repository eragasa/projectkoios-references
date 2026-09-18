-- Exact published schema-v2 layout from base 06f8ba63.
PRAGMA foreign_keys = ON;
CREATE TABLE catalog_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
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
    );
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
    );
CREATE TABLE candidate_source_observations (
        candidate_id TEXT NOT NULL,
        observation_id TEXT NOT NULL,
        PRIMARY KEY(candidate_id, observation_id),
        FOREIGN KEY(candidate_id) REFERENCES reference_candidates(candidate_id),
        FOREIGN KEY(observation_id)
            REFERENCES source_bibliography_observations(observation_id)
    );
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
    );
CREATE TABLE legacy_reference_records (
        citekey TEXT PRIMARY KEY,
        entry_type TEXT NOT NULL,
        title TEXT,
        authors_json TEXT NOT NULL,
        year TEXT,
        doi TEXT,
        isbn TEXT
    );
CREATE UNIQUE INDEX legacy_reference_doi_unique
        ON legacy_reference_records(doi) WHERE doi IS NOT NULL;
CREATE TABLE legacy_reference_aliases (
        alias TEXT PRIMARY KEY,
        canonical_citekey TEXT NOT NULL,
        rationale TEXT NOT NULL,
        FOREIGN KEY(canonical_citekey)
            REFERENCES legacy_reference_records(citekey)
    );
CREATE TABLE legacy_bibliography_occurrences (
        citekey TEXT NOT NULL,
        source_id TEXT NOT NULL,
        source_revision TEXT NOT NULL DEFAULT '',
        source_path TEXT NOT NULL,
        PRIMARY KEY(citekey, source_id, source_revision, source_path),
        FOREIGN KEY(citekey) REFERENCES legacy_reference_records(citekey)
    );
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
    );
CREATE TABLE legacy_review_memberships (
        collection_id TEXT NOT NULL,
        citekey TEXT NOT NULL,
        status TEXT NOT NULL,
        decision_note TEXT,
        PRIMARY KEY(collection_id, citekey)
    );
CREATE TABLE legacy_abstracts (
        citekey TEXT NOT NULL,
        provider TEXT NOT NULL,
        source_url TEXT NOT NULL,
        retrieved_at TEXT NOT NULL,
        language TEXT,
        content_hash TEXT NOT NULL,
        text TEXT NOT NULL,
        PRIMARY KEY(citekey, provider, content_hash)
    );
CREATE TABLE citation_candidates (
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
CREATE TABLE citation_edges (
        source_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        relation TEXT NOT NULL,
        source_locator TEXT NOT NULL,
        verification_status TEXT NOT NULL,
        PRIMARY KEY(source_id, target_id, relation, source_locator)
    );
INSERT INTO catalog_metadata(key, value) VALUES('schema_version', '2');
INSERT INTO catalog_metadata(key, value) VALUES('schema_fingerprint', 'catalog-schema:sha256:2e8db847387f06a003f56c375694000eee5be7edd32d4e7f0712267d1e3d0bc5');
