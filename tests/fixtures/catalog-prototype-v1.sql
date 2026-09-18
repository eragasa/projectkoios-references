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
INSERT INTO catalog_metadata(key, value) VALUES('schema_version', '1');
