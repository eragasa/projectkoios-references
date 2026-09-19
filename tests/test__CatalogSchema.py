from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest
from projectkoios.references.catalog import (
    CATALOG_SCHEMA_FINGERPRINT,
    CATALOG_SCHEMA_VERSION,
    SUPPORTED_CATALOG_SCHEMA_VERSIONS,
    CatalogConflictError,
    CatalogMigrationRequired,
    CatalogSchemaError,
    RootStorageClass,
)
from projectkoios.references.catalog import (
    ReferenceCatalog as _ReferenceCatalog,
)
from projectkoios.references.identity import (
    ProducerIdentity,
    ReferenceCandidate,
    SourceBibliographyObservation,
)
from projectkoios.references.models import SourceAssetRecord

_FIXTURES = Path(__file__).parent / "fixtures"


def ReferenceCatalog(path: Path) -> _ReferenceCatalog:
    return _ReferenceCatalog(path, storage_class=RootStorageClass.LOCAL)


def _database_dump(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        return "\n".join(connection.iterdump())


def _create_legacy(path: Path, fixture: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            (_FIXTURES / fixture).read_text(encoding="utf-8")
        )


def _identity_records(
    *,
    citekey: str = "complete2026",
    source_observation_ids: tuple[str, ...] | None = None,
) -> tuple[SourceBibliographyObservation, ReferenceCandidate]:
    bibliography = (
        f"@article{{{citekey}, title={{Complete record}}, year={{2026}}}}\n"
    ).encode()
    observation = SourceBibliographyObservation.create(
        source_id="synthetic-fixture",
        asserted_source_revision="asserted-revision",
        source_path="references.bib",
        bibliography_bytes=bibliography,
        entry_index=0,
        observed_citekey=citekey,
        verbatim_entry=bibliography.decode().strip(),
        parser=ProducerIdentity("fixture-parser", "2"),
    )
    candidate = ReferenceCandidate.create(
        proposed_citekey=citekey,
        entry_type="article",
        title="Complete record",
        authors=("Example, Ada", "Example, Ben"),
        year="2026",
        doi="10.1234/complete",
        isbn="978-0-00-000000-0",
        url="https://example.test/complete",
        eprint="arXiv:2601.00001",
        source_observation_ids=(
            source_observation_ids
            if source_observation_ids is not None
            else (observation.observation_id,)
        ),
        generator=ProducerIdentity("fixture-normalizer", "3"),
    )
    return observation, candidate


def _populate_identity_v1(
    path: Path,
) -> tuple[SourceBibliographyObservation, ReferenceCandidate]:
    observation, candidate = _identity_records()
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO source_bibliography_observations(
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
        connection.execute(
            """
            INSERT INTO reference_candidates(
                candidate_id, authority_kind, lifecycle_status,
                proposed_citekey, citekey_status, candidate_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.candidate_id,
                candidate.authority_kind,
                candidate.lifecycle_status,
                candidate.proposed_citekey,
                candidate.citekey_status,
                candidate.to_json(),
            ),
        )
        connection.execute(
            """
            INSERT INTO candidate_source_observations(
                candidate_id, observation_id
            ) VALUES (?, ?)
            """,
            (candidate.candidate_id, observation.observation_id),
        )
        connection.execute(
            """
            INSERT INTO candidate_source_assets(
                candidate_id, proposed_citekey, identity_status,
                citekey_status, sha256, byte_size, root_alias,
                relative_path, rights_status, asset_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.candidate_id,
                candidate.proposed_citekey,
                candidate.lifecycle_status,
                candidate.citekey_status,
                "a" * 64,
                100,
                "papers",
                "complete.candidate.pdf",
                "unreviewed",
                "located-candidate",
            ),
        )
        connection.execute(
            """
            INSERT INTO reference_records(
                citekey, entry_type, title, authors_json, year, doi, isbn
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.proposed_citekey,
                candidate.entry_type,
                candidate.title,
                json.dumps(candidate.authors),
                candidate.year,
                candidate.doi,
                candidate.isbn,
            ),
        )
    return observation, candidate


def _populate_published_v2(
    path: Path,
) -> tuple[SourceBibliographyObservation, ReferenceCandidate]:
    observation, candidate = _identity_records(citekey="publishedV2")
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO source_bibliography_observations(
                observation_id, record_schema_version, authority_kind,
                source_id, asserted_source_revision, source_path,
                bibliography_sha256, bibliography_byte_size, entry_index,
                observed_citekey, verbatim_entry, parser_name,
                parser_version, observation_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
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
            ),
        )
        connection.execute(
            """
            INSERT INTO reference_candidates(
                candidate_id, record_schema_version, authority_kind,
                lifecycle_status, proposed_citekey, citekey_status,
                entry_type, title, authors_json, year, doi, isbn, url,
                eprint, generator_name, generator_version, candidate_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.candidate_id,
                candidate.schema_version,
                candidate.authority_kind,
                candidate.lifecycle_status,
                candidate.proposed_citekey,
                candidate.citekey_status,
                candidate.entry_type,
                candidate.title,
                json.dumps(
                    candidate.authors,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                candidate.year,
                candidate.doi,
                candidate.isbn,
                candidate.url,
                candidate.eprint,
                candidate.generator.name,
                candidate.generator.version,
                candidate.to_json(),
            ),
        )
        connection.execute(
            """
            INSERT INTO candidate_source_observations(
                candidate_id, observation_id
            ) VALUES (?, ?)
            """,
            (candidate.candidate_id, observation.observation_id),
        )
        connection.execute(
            """
            INSERT INTO candidate_source_assets(
                candidate_id, proposed_citekey, identity_status,
                citekey_status, sha256, byte_size, root_alias,
                relative_path, rights_status, asset_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.candidate_id,
                candidate.proposed_citekey,
                candidate.lifecycle_status,
                candidate.citekey_status,
                "a" * 64,
                100,
                "papers",
                "published-v2.pdf",
                "unreviewed",
                "located-candidate",
            ),
        )
        connection.execute(
            """
            INSERT INTO legacy_reference_records(
                citekey, entry_type, title, authors_json, year, doi, isbn
            ) VALUES ('legacyV2', 'article', 'Legacy v2', '["Ada"]',
                      '2020', NULL, NULL)
            """
        )
        connection.execute(
            """
            INSERT INTO legacy_reference_aliases(
                alias, canonical_citekey, rationale
            ) VALUES ('legacyV2Alias', 'legacyV2', 'published v2 row')
            """
        )
        connection.execute(
            """
            INSERT INTO legacy_bibliography_occurrences(
                citekey, source_id, source_revision, source_path
            ) VALUES ('legacyV2', 'legacy-source', 'revision',
                      'references.bib')
            """
        )
        connection.execute(
            """
            INSERT INTO legacy_source_assets(
                citekey, sha256, byte_size, root_alias, relative_path,
                rights_status, asset_status
            ) VALUES ('legacyV2', ?, 10, 'papers', 'legacy-v2.pdf',
                      'unreviewed', 'legacy-row')
            """,
            ("b" * 64,),
        )
        connection.execute(
            """
            INSERT INTO legacy_review_memberships(
                collection_id, citekey, status, decision_note
            ) VALUES ('legacy-v2-review', 'legacyV2', 'discovered', NULL)
            """
        )
        connection.execute(
            """
            INSERT INTO legacy_abstracts(
                citekey, provider, source_url, retrieved_at, language,
                content_hash, text
            ) VALUES ('legacyV2', 'fixture', 'https://example.test/',
                      '2026-01-01', 'en', ?, 'legacy v2 abstract')
            """,
            ("c" * 64,),
        )
        connection.execute(
            """
            INSERT INTO citation_candidates(
                candidate_id, proposed_citekey, title, authors, year, doi,
                metadata_status, abstract_status, abstract
            ) VALUES ('legacy.v2.graph', 'legacyV2Graph', 'Legacy v2 graph',
                      'Ada', '2020', NULL, 'transcribed', 'not-requested', NULL)
            """
        )
        connection.execute(
            """
            INSERT INTO citation_edges(
                source_id, target_id, relation, source_locator,
                verification_status
            ) VALUES ('legacy-v2-source', 'legacy.v2.graph', 'cites',
                      'References [1]', 'unverified')
            """
        )
    return observation, candidate


def _populate_published_v3(
    path: Path,
) -> tuple[SourceBibliographyObservation, ReferenceCandidate]:
    observation, candidate = _identity_records(citekey="publishedV3")
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO source_bibliography_observations(
                observation_id, record_schema_version, authority_kind,
                source_id, asserted_source_revision, source_path,
                bibliography_sha256, bibliography_byte_size, entry_index,
                observed_citekey, verbatim_entry, parser_name,
                parser_version, observation_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
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
            ),
        )
        connection.execute(
            """
            INSERT INTO reference_candidates(
                candidate_id, record_schema_version, authority_kind,
                lifecycle_status, proposed_citekey, citekey_status,
                entry_type, title, authors_json, year, doi, isbn, url,
                eprint, generator_name, generator_version, candidate_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.candidate_id,
                candidate.schema_version,
                candidate.authority_kind,
                candidate.lifecycle_status,
                candidate.proposed_citekey,
                candidate.citekey_status,
                candidate.entry_type,
                candidate.title,
                json.dumps(
                    candidate.authors,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                candidate.year,
                candidate.doi,
                candidate.isbn,
                candidate.url,
                candidate.eprint,
                candidate.generator.name,
                candidate.generator.version,
                candidate.to_json(),
            ),
        )
        connection.execute(
            """
            INSERT INTO candidate_source_observations(
                candidate_id, observation_id
            ) VALUES (?, ?)
            """,
            (candidate.candidate_id, observation.observation_id),
        )
        connection.execute(
            """
            INSERT INTO legacy_review_memberships(
                collection_id, citekey, status, decision_note
            ) VALUES ('legacy-v3-review', 'publishedV3',
                      'human-accepted', 'unprovenanced legacy scalar')
            """
        )
    return observation, candidate


def test__catalog_schema__is_explicit_deterministic_and_idempotent(
    tmp_path: Path,
) -> None:
    first = ReferenceCatalog(tmp_path / "first.sqlite3")
    second = ReferenceCatalog(tmp_path / "second.sqlite3")

    first_info = first.initialize()
    second_info = second.initialize()

    assert CATALOG_SCHEMA_VERSION == 4
    assert SUPPORTED_CATALOG_SCHEMA_VERSIONS == (4,)
    assert CATALOG_SCHEMA_FINGERPRINT == (
        "catalog-schema:sha256:"
        "30bb68e78832c461011f7e2a9ba7812c93aa099c866a84869a8415500f415e48"
    )
    assert re.fullmatch(
        r"catalog-schema:sha256:[0-9a-f]{64}",
        CATALOG_SCHEMA_FINGERPRINT,
    )
    assert first_info == second_info == first.schema_info()
    assert first.initialize() == first_info
    with sqlite3.connect(first.path) as connection:
        metadata = dict(
            connection.execute(
                "SELECT key, value FROM catalog_metadata"
            ).fetchall()
        )
    assert metadata == {
        "schema_version": "4",
        "schema_fingerprint": CATALOG_SCHEMA_FINGERPRINT,
    }


@pytest.mark.parametrize(
    "mutation",
    (
        "newer-version",
        "noncanonical-version",
        "altered-fingerprint",
        "missing-column",
        "extra-column",
        "missing-index",
        "extra-index",
        "extra-trigger",
    ),
)
def test__catalog_schema__rejects_divergent_current_schema_without_mutation(
    tmp_path: Path,
    mutation: str,
) -> None:
    path = tmp_path / f"{mutation}.sqlite3"
    catalog = ReferenceCatalog(path)
    catalog.initialize()
    with sqlite3.connect(path) as connection:
        if mutation == "newer-version":
            connection.execute(
                "UPDATE catalog_metadata SET value = '99' "
                "WHERE key = 'schema_version'"
            )
        elif mutation == "noncanonical-version":
            connection.execute(
                "UPDATE catalog_metadata SET value = '02' "
                "WHERE key = 'schema_version'"
            )
        elif mutation == "altered-fingerprint":
            connection.execute(
                "UPDATE catalog_metadata SET value = ? "
                "WHERE key = 'schema_fingerprint'",
                ("catalog-schema:sha256:" + "0" * 64,),
            )
        elif mutation == "missing-column":
            connection.execute(
                "ALTER TABLE reference_candidates DROP COLUMN url"
            )
        elif mutation == "extra-column":
            connection.execute(
                "ALTER TABLE reference_candidates ADD COLUMN extra TEXT"
            )
        elif mutation == "missing-index":
            connection.execute("DROP INDEX legacy_reference_doi_unique")
        elif mutation == "extra-index":
            connection.execute(
                "CREATE INDEX unexpected_index "
                "ON reference_candidates(proposed_citekey)"
            )
        else:
            connection.execute(
                """
                CREATE TRIGGER unexpected_trigger
                AFTER INSERT ON reference_candidates
                BEGIN
                    SELECT 1;
                END
                """
            )
    before = _database_dump(path)

    with pytest.raises(CatalogSchemaError):
        catalog.initialize()

    assert _database_dump(path) == before


def test__catalog_schema__rejects_version_fingerprint_mismatch(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mismatched-version.sqlite3"
    _create_legacy(path, "catalog-published-v2.sql")
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE catalog_metadata SET value = '3' "
            "WHERE key = 'schema_version'"
        )
    before = _database_dump(path)

    with pytest.raises(CatalogSchemaError, match="belongs to published-v2"):
        ReferenceCatalog(path).migration_plan()

    assert _database_dump(path) == before


def test__catalog_schema__rejects_unknown_or_incomplete_version_one(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unknown.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE catalog_metadata(key TEXT PRIMARY KEY, value TEXT)"
        )
        connection.execute(
            "INSERT INTO catalog_metadata VALUES('schema_version', '1')"
        )
        connection.execute("CREATE TABLE unexpected(value TEXT)")
    before = _database_dump(path)

    with pytest.raises(CatalogSchemaError, match="unknown or altered"):
        ReferenceCatalog(path).initialize()

    assert _database_dump(path) == before


@pytest.mark.parametrize(
    ("fixture", "source_version", "source_kind", "source_fingerprint"),
    (
        (
            "catalog-prototype-v1.sql",
            1,
            "prototype-v1",
            "catalog-schema:sha256:"
            "5714c33eba9eb9638c0735dff5824058d7c77115a3a5c62f97486e0da41d771b",
        ),
        (
            "catalog-identity-v1.sql",
            1,
            "identity-v1",
            "catalog-schema:sha256:"
            "b6280d710df8e1cabdcdec99847a927135a49b9e833d3cb84c5e9bf44ce845c8",
        ),
        (
            "catalog-published-v2.sql",
            2,
            "published-v2",
            "catalog-schema:sha256:"
            "2e8db847387f06a003f56c375694000eee5be7edd32d4e7f0712267d1e3d0bc5",
        ),
        (
            "catalog-published-v3.sql",
            3,
            "published-v3",
            "catalog-schema:sha256:"
            "d2970cd39caff4971407ea11b9ab4ea630d53c0b11e1b0dd58a65f045c0bffaa",
        ),
    ),
)
def test__catalog_schema__known_legacy_requires_backup_and_explicit_migration(
    tmp_path: Path,
    fixture: str,
    source_version: int,
    source_kind: str,
    source_fingerprint: str,
) -> None:
    path = tmp_path / "legacy.sqlite3"
    _create_legacy(path, fixture)
    catalog = ReferenceCatalog(path)
    before = _database_dump(path)

    plan = catalog.migration_plan()
    assert plan is not None
    assert plan.source_schema_version == source_version
    assert plan.source_kind == source_kind
    assert plan.source_schema_fingerprint == source_fingerprint
    assert plan.target_schema_version == CATALOG_SCHEMA_VERSION
    assert plan.target_schema_fingerprint == CATALOG_SCHEMA_FINGERPRINT
    assert plan.backup_required is True
    with pytest.raises(CatalogMigrationRequired, match="external backup"):
        catalog.initialize()
    with pytest.raises(CatalogMigrationRequired, match="backup_confirmed"):
        catalog.migrate()

    assert _database_dump(path) == before


def test__catalog_migration__quarantines_prototype_rows_without_promotion(
    tmp_path: Path,
) -> None:
    path = tmp_path / "prototype.sqlite3"
    _create_legacy(path, "catalog-prototype-v1.sql")
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO reference_records(
                citekey, entry_type, title, authors_json, year, doi, isbn
            ) VALUES ('legacyKey', 'article', 'Legacy', '["Ada"]',
                      '2020', NULL, NULL)
            """
        )
        connection.execute(
            """
            INSERT INTO reference_aliases(alias, canonical_citekey, rationale)
            VALUES ('oldKey', 'legacyKey', 'legacy unprovenanced row')
            """
        )
        connection.execute(
            """
            INSERT INTO bibliography_occurrences(
                citekey, source_id, source_revision, source_path
            ) VALUES ('legacyKey', 'legacy-source', 'legacy-revision',
                      'references.bib')
            """
        )
        connection.execute(
            """
            INSERT INTO source_assets(
                citekey, sha256, byte_size, root_alias, relative_path,
                rights_status, asset_status
            ) VALUES ('legacyKey', ?, 10, 'papers', 'legacy.pdf',
                      'unreviewed', 'legacy-row')
            """,
            ("d" * 64,),
        )
        connection.execute(
            """
            INSERT INTO review_memberships(
                collection_id, citekey, status, decision_note
            ) VALUES ('legacy-review', 'legacyKey', 'discovered', NULL)
            """
        )
        connection.execute(
            """
            INSERT INTO abstracts(
                citekey, provider, source_url, retrieved_at, language,
                content_hash, text
            ) VALUES ('legacyKey', 'fixture', 'https://example.test/',
                      '2026-01-01', 'en', ?, 'legacy abstract')
            """,
            ("e" * 64,),
        )
        connection.execute(
            """
            INSERT INTO citation_candidates(
                candidate_id, proposed_citekey, title, authors, year, doi,
                metadata_status, abstract_status, abstract
            ) VALUES ('legacy.graph.1', 'legacyGraph', 'Legacy graph', NULL,
                      '2020', NULL, 'transcribed', 'not-requested', NULL)
            """
        )
        connection.execute(
            """
            INSERT INTO citation_edges(
                source_id, target_id, relation, source_locator,
                verification_status
            ) VALUES ('legacy-source', 'legacy.graph.1', 'cites',
                      'References [1]', 'unverified')
            """
        )
    catalog = ReferenceCatalog(path)

    catalog.migrate(backup_confirmed=True)

    assert catalog.read_observations() == ()
    assert catalog.read_candidates() == ()
    counts = catalog.counts()
    assert counts["legacy_reference_rows"] == 1
    assert counts["unprovenanced_alias_rows"] == 1
    assert counts["review_memberships"] == 1
    assert counts["abstracts"] == 1
    assert counts["citation_source_observations"] == 0
    assert counts["citation_candidates"] == 0
    assert counts["citation_edges"] == 0
    assert counts["legacy_citation_candidates"] == 1
    assert counts["legacy_citation_edges"] == 1
    with sqlite3.connect(path) as connection:
        legacy = connection.execute(
            "SELECT citekey, title FROM legacy_reference_records"
        ).fetchall()
        preserved_counts = {
            table: connection.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            ).fetchone()[0]
            for table in (
                "legacy_bibliography_occurrences",
                "legacy_source_assets",
                "legacy_review_memberships",
                "legacy_abstracts",
            )
        }
        metadata = dict(
            connection.execute(
                "SELECT key, value FROM catalog_metadata"
            ).fetchall()
        )
    assert legacy == [("legacyKey", "Legacy")]
    assert preserved_counts == {
        "legacy_bibliography_occurrences": 1,
        "legacy_source_assets": 1,
        "legacy_review_memberships": 1,
        "legacy_abstracts": 1,
    }
    assert metadata["schema_fingerprint"] == CATALOG_SCHEMA_FINGERPRINT


def test__catalog_migration__preserves_complete_identity_records(
    tmp_path: Path,
) -> None:
    path = tmp_path / "identity.sqlite3"
    _create_legacy(path, "catalog-identity-v1.sql")
    observation, candidate = _populate_identity_v1(path)
    catalog = ReferenceCatalog(path)

    catalog.migrate(backup_confirmed=True)

    assert catalog.read_observations() == (observation,)
    assert catalog.read_candidates() == (candidate,)
    assert catalog.read_candidates()[0].url == "https://example.test/complete"
    assert catalog.read_candidates()[0].eprint == "arXiv:2601.00001"
    assert catalog.counts()["source_assets"] == 1
    assert catalog.counts()["legacy_reference_rows"] == 1
    assert catalog.migrate() == catalog.schema_info()


def test__catalog_migration__preserves_published_v2_and_quarantines_graph(
    tmp_path: Path,
) -> None:
    path = tmp_path / "published-v2.sqlite3"
    _create_legacy(path, "catalog-published-v2.sql")
    observation, candidate = _populate_published_v2(path)
    table_map = {
        "legacy_reference_records": "legacy_reference_records",
        "legacy_reference_aliases": "legacy_reference_aliases",
        "legacy_bibliography_occurrences": ("legacy_bibliography_occurrences"),
        "legacy_source_assets": "legacy_source_assets",
        "legacy_review_memberships": "legacy_review_memberships",
        "legacy_abstracts": "legacy_abstracts",
        "citation_candidates": "legacy_citation_candidates",
        "citation_edges": "legacy_citation_edges",
    }
    with sqlite3.connect(path) as connection:
        expected = {
            target: connection.execute(
                f'SELECT * FROM "{source}" ORDER BY rowid'
            ).fetchall()
            for source, target in table_map.items()
        }
    catalog = ReferenceCatalog(path)

    catalog.migrate(backup_confirmed=True)

    assert catalog.schema_info().schema_version == 4
    assert catalog.read_observations() == (observation,)
    assert catalog.read_candidates() == (candidate,)
    assert catalog.counts()["source_assets"] == 1
    assert catalog.read_citation_graph().sources == ()
    with sqlite3.connect(path) as connection:
        actual = {
            target: connection.execute(
                f'SELECT * FROM "{target}" ORDER BY rowid'
            ).fetchall()
            for target in table_map.values()
        }
        metadata = dict(
            connection.execute(
                "SELECT key, value FROM catalog_metadata"
            ).fetchall()
        )
    assert actual == expected
    assert metadata == {
        "schema_version": "4",
        "schema_fingerprint": CATALOG_SCHEMA_FINGERPRINT,
    }


def test__catalog_migration__preserves_schema_v3_without_authority_upgrade(
    tmp_path: Path,
) -> None:
    path = tmp_path / "published-v3.sqlite3"
    _create_legacy(path, "catalog-published-v3.sql")
    observation, candidate = _populate_published_v3(path)
    catalog = ReferenceCatalog(path)

    plan = catalog.migration_plan()
    assert plan is not None
    assert plan.source_schema_version == 3
    assert plan.source_schema_fingerprint == (
        "catalog-schema:sha256:"
        "d2970cd39caff4971407ea11b9ab4ea630d53c0b11e1b0dd58a65f045c0bffaa"
    )
    catalog.migrate(backup_confirmed=True)

    assert catalog.read_observations() == (observation,)
    assert catalog.read_candidates() == (candidate,)
    assert catalog.read_review_projection().human_decision_history == ()
    with sqlite3.connect(path) as connection:
        legacy = connection.execute(
            """
            SELECT collection_id, citekey, status, decision_note
            FROM legacy_review_memberships
            """
        ).fetchall()
    assert legacy == [
        (
            "legacy-v3-review",
            "publishedV3",
            "human-accepted",
            "unprovenanced legacy scalar",
        )
    ]


def test__catalog_migration__published_v2_failure_restores_exact_database(
    tmp_path: Path,
) -> None:
    path = tmp_path / "published-v2-rollback.sqlite3"
    _create_legacy(path, "catalog-published-v2.sql")
    _populate_published_v2(path)
    catalog = ReferenceCatalog(path)
    before = _database_dump(path)

    def fail_after_target_verified(step: str) -> None:
        if step == "target-verified":
            raise RuntimeError("induced v2 migration failure")

    catalog._migration_checkpoint = fail_after_target_verified  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="induced v2 migration failure"):
        catalog.migrate(backup_confirmed=True)

    assert _database_dump(path) == before
    plan = catalog.migration_plan()
    assert plan is not None
    assert plan.source_schema_version == 2
    assert plan.source_kind == "published-v2"


def test__catalog_schema__altered_published_v2_fails_closed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "altered-published-v2.sqlite3"
    _create_legacy(path, "catalog-published-v2.sql")
    with sqlite3.connect(path) as connection:
        connection.execute(
            "ALTER TABLE citation_edges ADD COLUMN unexpected TEXT"
        )
    before = _database_dump(path)

    with pytest.raises(CatalogSchemaError, match="differs from its actual"):
        ReferenceCatalog(path).migration_plan()

    assert _database_dump(path) == before


def test__catalog_migration__mid_migration_failure_rolls_back_schema_and_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rollback.sqlite3"
    _create_legacy(path, "catalog-identity-v1.sql")
    _populate_identity_v1(path)
    catalog = ReferenceCatalog(path)
    before = _database_dump(path)

    def fail_after_target_verified(step: str) -> None:
        if step == "target-verified":
            raise RuntimeError("induced migration failure")

    catalog._migration_checkpoint = fail_after_target_verified  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="induced migration failure"):
        catalog.migrate(backup_confirmed=True)

    assert _database_dump(path) == before
    assert catalog.migration_plan() is not None


def test__catalog_import__mid_batch_failure_rolls_back_every_row(
    tmp_path: Path,
) -> None:
    catalog = ReferenceCatalog(tmp_path / "rollback.sqlite3")
    catalog.initialize()
    observation, first = _identity_records(citekey="first2026")
    _, second = _identity_records(
        citekey="second2026",
        source_observation_ids=("bibliography-observation:sha256:" + "f" * 64,),
    )

    with pytest.raises(CatalogConflictError, match="schema integrity"):
        catalog.import_candidates((first, second), (observation,))

    assert catalog.read_observations() == ()
    assert catalog.read_candidates() == ()


def test__catalog_import__conflicting_asset_batch_rolls_back_first_row(
    tmp_path: Path,
) -> None:
    catalog = ReferenceCatalog(tmp_path / "assets.sqlite3")
    catalog.initialize()
    observation, candidate = _identity_records()
    catalog.import_candidates((candidate,), (observation,))
    common = {
        "candidate_id": candidate.candidate_id,
        "proposed_citekey": candidate.proposed_citekey,
        "identity_status": candidate.lifecycle_status,
        "citekey_status": candidate.citekey_status,
        "sha256": "b" * 64,
        "byte_size": 10,
        "root_alias": "papers",
        "rights_status": "unreviewed",
        "asset_status": "located-candidate",
    }
    first = SourceAssetRecord(relative_path="first.pdf", **common)
    conflicting = SourceAssetRecord(relative_path="second.pdf", **common)

    with pytest.raises(CatalogConflictError, match="existing evidence"):
        catalog.record_source_assets((first, conflicting))

    assert catalog.counts()["source_assets"] == 0


def test__catalog_reads__reject_content_identity_mismatch(
    tmp_path: Path,
) -> None:
    path = tmp_path / "identity-mismatch.sqlite3"
    catalog = ReferenceCatalog(path)
    catalog.initialize()
    observation, candidate = _identity_records()
    catalog.import_candidates((candidate,), (observation,))
    data = json.loads(candidate.to_json())
    data["candidate_id"] = "reference-candidate:sha256:" + "0" * 64
    tampered = (
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE reference_candidates SET candidate_json = ?",
            (tampered,),
        )

    with pytest.raises(CatalogSchemaError, match="invalid canonical JSON"):
        catalog.read_candidates()


@pytest.mark.parametrize("byte_size", (1.5, True))
def test__source_asset__rejects_non_integer_byte_size(
    byte_size: object,
) -> None:
    _, candidate = _identity_records()
    with pytest.raises(ValueError, match="non-negative integer"):
        SourceAssetRecord(
            candidate_id=candidate.candidate_id,
            proposed_citekey=candidate.proposed_citekey,
            identity_status=candidate.lifecycle_status,
            citekey_status=candidate.citekey_status,
            sha256="f" * 64,
            byte_size=byte_size,  # type: ignore[arg-type]
            root_alias="papers",
            relative_path="candidate.pdf",
            rights_status="unreviewed",
            asset_status="located-candidate",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("rights_status", 123),
        ("rights_status", False),
        ("rights_status", ""),
        ("rights_status", "x" * 4097),
        ("asset_status", 123),
        ("asset_status", False),
        ("asset_status", ""),
        ("asset_status", "x" * 4097),
    ),
)
def test__source_asset__rejects_invalid_status_fields(
    field: str,
    value: object,
) -> None:
    _, candidate = _identity_records()
    statuses: dict[str, object] = {
        "rights_status": "unreviewed",
        "asset_status": "located-candidate",
    }
    statuses[field] = value
    with pytest.raises(ValueError, match="bounded non-empty string"):
        SourceAssetRecord(
            candidate_id=candidate.candidate_id,
            proposed_citekey=candidate.proposed_citekey,
            identity_status=candidate.lifecycle_status,
            citekey_status=candidate.citekey_status,
            sha256="f" * 64,
            byte_size=10,
            root_alias="papers",
            relative_path="candidate.pdf",
            rights_status=statuses["rights_status"],  # type: ignore[arg-type]
            asset_status=statuses["asset_status"],  # type: ignore[arg-type]
        )


def test__catalog_schema__rejects_real_candidate_asset_byte_size(
    tmp_path: Path,
) -> None:
    path = tmp_path / "real-byte-size.sqlite3"
    catalog = ReferenceCatalog(path)
    catalog.initialize()
    observation, candidate = _identity_records()
    catalog.import_candidates((candidate,), (observation,))

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
            connection.execute(
                """
                INSERT INTO candidate_source_assets(
                    candidate_id, proposed_citekey, identity_status,
                    citekey_status, sha256, byte_size, root_alias,
                    relative_path, rights_status, asset_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.candidate_id,
                    candidate.proposed_citekey,
                    candidate.lifecycle_status,
                    candidate.citekey_status,
                    "f" * 64,
                    1.5,
                    "papers",
                    "candidate.pdf",
                    "unreviewed",
                    "located-candidate",
                ),
            )

    assert catalog.counts()["source_assets"] == 0


def test__catalog_reads__reject_asset_candidate_inconsistency(
    tmp_path: Path,
) -> None:
    path = tmp_path / "asset-mismatch.sqlite3"
    catalog = ReferenceCatalog(path)
    catalog.initialize()
    observation, candidate = _identity_records()
    catalog.import_candidates((candidate,), (observation,))
    catalog.record_source_asset(
        SourceAssetRecord(
            candidate_id=candidate.candidate_id,
            proposed_citekey=candidate.proposed_citekey,
            identity_status=candidate.lifecycle_status,
            citekey_status=candidate.citekey_status,
            sha256="c" * 64,
            byte_size=10,
            root_alias="papers",
            relative_path="candidate.pdf",
            rights_status="unreviewed",
            asset_status="located-candidate",
        )
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE candidate_source_assets SET proposed_citekey = 'otherKey'"
        )

    with pytest.raises(CatalogSchemaError, match="candidate identity"):
        catalog.counts()


def test__catalog_reads__reject_scalar_json_and_foreign_key_inconsistency(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invalid.sqlite3"
    catalog = ReferenceCatalog(path)
    catalog.initialize()
    observation, candidate = _identity_records()
    catalog.import_candidates((candidate,), (observation,))
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE reference_candidates SET url = 'https://changed.test/'"
        )

    with pytest.raises(CatalogSchemaError, match="canonical JSON"):
        catalog.read_candidates()

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE reference_candidates SET url = ?",
            (candidate.url,),
        )
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            """
            INSERT INTO candidate_source_assets(
                candidate_id, proposed_citekey, identity_status,
                citekey_status, sha256, byte_size, root_alias,
                relative_path, rights_status, asset_status
            ) VALUES (?, 'orphan', 'unaccepted-candidate',
                      'proposed-noncanonical', ?, 1, 'papers',
                      'orphan.pdf', 'unreviewed', 'located-candidate')
            """,
            (
                "reference-candidate:sha256:" + "e" * 64,
                "e" * 64,
            ),
        )

    with pytest.raises(CatalogSchemaError, match="foreign-key"):
        catalog.counts()


def test__catalog_migration__real_legacy_asset_size_rolls_back_unchanged(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-real-byte-size.sqlite3"
    _create_legacy(path, "catalog-identity-v1.sql")
    _, candidate = _populate_identity_v1(path)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE candidate_source_assets SET byte_size = 1.5")
    before = _database_dump(path)

    with pytest.raises(CatalogSchemaError, match="not stored as an integer"):
        ReferenceCatalog(path).migrate(backup_confirmed=True)

    assert _database_dump(path) == before
    assert ReferenceCatalog(path).migration_plan() is not None


def test__catalog_migration__invalid_legacy_identity_fails_without_changes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invalid-legacy.sqlite3"
    _create_legacy(path, "catalog-identity-v1.sql")
    _populate_identity_v1(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE reference_candidates SET candidate_json = '{}'"
        )
    before = _database_dump(path)

    with pytest.raises(CatalogSchemaError, match="canonical JSON"):
        ReferenceCatalog(path).migrate(backup_confirmed=True)

    assert _database_dump(path) == before
