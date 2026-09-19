BEGIN TRANSACTION;
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
CREATE TABLE candidate_source_observations (
        candidate_id TEXT NOT NULL,
        observation_id TEXT NOT NULL,
        PRIMARY KEY(candidate_id, observation_id),
        FOREIGN KEY(candidate_id) REFERENCES reference_candidates(candidate_id),
        FOREIGN KEY(observation_id)
            REFERENCES source_bibliography_observations(observation_id)
    );
CREATE TABLE catalog_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
INSERT INTO "catalog_metadata" VALUES('schema_version','4');
INSERT INTO "catalog_metadata" VALUES('schema_fingerprint','catalog-schema:sha256:30bb68e78832c461011f7e2a9ba7812c93aa099c866a84869a8415500f415e48');
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
    );
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
    );
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
    );
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
CREATE TABLE legacy_bibliography_occurrences (
        citekey TEXT NOT NULL,
        source_id TEXT NOT NULL,
        source_revision TEXT NOT NULL DEFAULT '',
        source_path TEXT NOT NULL,
        PRIMARY KEY(citekey, source_id, source_revision, source_path),
        FOREIGN KEY(citekey) REFERENCES legacy_reference_records(citekey)
    );
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
    );
CREATE TABLE legacy_citation_edges (
        source_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        relation TEXT NOT NULL,
        source_locator TEXT NOT NULL,
        verification_status TEXT NOT NULL,
        PRIMARY KEY(source_id, target_id, relation, source_locator)
    );
CREATE TABLE legacy_reference_aliases (
        alias TEXT PRIMARY KEY,
        canonical_citekey TEXT NOT NULL,
        rationale TEXT NOT NULL,
        FOREIGN KEY(canonical_citekey)
            REFERENCES legacy_reference_records(citekey)
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
CREATE TABLE legacy_review_memberships (
        collection_id TEXT NOT NULL,
        citekey TEXT NOT NULL,
        status TEXT NOT NULL,
        decision_note TEXT,
        PRIMARY KEY(collection_id, citekey)
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
    );
CREATE UNIQUE INDEX legacy_reference_doi_unique
        ON legacy_reference_records(doi) WHERE doi IS NOT NULL
    ;
COMMIT;
