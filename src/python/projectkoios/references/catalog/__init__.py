from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from projectkoios.references.graph import CitationGraph
from projectkoios.references.identity import (
    ReferenceCandidate,
    SourceBibliographyObservation,
)
from projectkoios.references.models import AbstractRecord, SourceAssetRecord
from projectkoios.references.path_safety import (
    CloudPlaceholderProbe,
    CloudRootMutationError,
    RootStorageClass,
)
from projectkoios.references.review import (
    HumanReviewDecision,
    ReviewProjection,
    ReviewRecordError,
    TechnicalReviewRecord,
    replay_review_records,
)
from projectkoios.references.state_projection import ReferenceStateProjection

from ._internals import _CatalogInternals
from .schema import (
    _AUTHORITY_BOUNDARY,
    _KNOWN_LEGACY_SCHEMAS,
    _LEGACY_DROP_ORDER,
    _MAX_STATE_PROJECTION_EXPORT_BYTES,
    _MAX_STATE_PROJECTION_JSON_BYTES,
    _MAX_STATE_PROJECTIONS,
    CATALOG_SCHEMA_FINGERPRINT,
    CATALOG_SCHEMA_VERSION,
    SUPPORTED_CATALOG_SCHEMA_VERSIONS,
    CandidateConflictError,
    CatalogConflictError,
    CatalogError,
    CatalogMigrationPlan,
    CatalogMigrationRequired,
    CatalogSchemaError,
    CatalogSchemaInfo,
)
from .serialization import (
    _CANDIDATE_COLUMNS,
    _GRAPH_CANDIDATE_COLUMNS,
    _GRAPH_EDGE_COLUMNS,
    _GRAPH_SOURCE_COLUMNS,
    _HUMAN_REVIEW_COLUMNS,
    _OBSERVATION_COLUMNS,
    _STATE_PROJECTION_COLUMNS,
    _TECHNICAL_REVIEW_COLUMNS,
    _asset_values,
    _bounded_review_inputs,
    _bounded_state_projection_inputs,
    _candidate_values,
    _graph_candidate_values,
    _graph_edge_values,
    _graph_source_values,
    _human_review_values,
    _observation_values,
    _state_projection_values,
    _technical_review_values,
)

__all__ = [
    "CATALOG_SCHEMA_FINGERPRINT",
    "CATALOG_SCHEMA_VERSION",
    "SUPPORTED_CATALOG_SCHEMA_VERSIONS",
    "CandidateConflictError",
    "CatalogConflictError",
    "CatalogError",
    "CatalogMigrationPlan",
    "CatalogMigrationRequired",
    "CatalogSchemaError",
    "CatalogSchemaInfo",
    "ReferenceCatalog",
]

for _public_type in (
    CandidateConflictError,
    CatalogConflictError,
    CatalogError,
    CatalogMigrationPlan,
    CatalogMigrationRequired,
    CatalogSchemaError,
    CatalogSchemaInfo,
):
    _public_type.__module__ = __name__
del _public_type


class ReferenceCatalog(_CatalogInternals):
    """SQLite working projection; immutable records remain authoritative."""

    def __init__(
        self,
        path: Path,
        *,
        storage_class: RootStorageClass,
        placeholder_probe: CloudPlaceholderProbe | None = None,
    ) -> None:
        if storage_class is RootStorageClass.CLOUD_BACKED:
            raise CloudRootMutationError(
                "SQLite catalogs require an explicitly local staging path"
            )
        self.path = path
        self.storage_class = storage_class
        self.placeholder_probe = placeholder_probe

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

    @contextmanager
    def source_asset_recording_transaction(
        self, asset: SourceAssetRecord
    ) -> Iterator[None]:
        """Hold an exact catalog preflight through one external operation."""
        if not isinstance(asset, SourceAssetRecord):
            raise TypeError("asset must be a SourceAssetRecord")
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
        values = _asset_values(asset)
        with self._write_transaction() as connection:
            # Validate every current-generation invariant before the caller is
            # allowed to perform its external mutation. BEGIN IMMEDIATE keeps
            # another catalog writer from invalidating this preflight.
            self._require_foreign_keys(connection)
            self._validate_identity_rows(connection)
            self._validate_graph_rows(connection)
            self._validate_review_rows(connection)
            self._validate_state_projection_rows(connection)
            observations = self._read_observations(connection)
            candidate_by_id = {
                item.candidate_id: item
                for item in self._read_candidates(
                    connection,
                    {item.observation_id for item in observations},
                )
            }
            self._require_asset_candidate_match(
                asset,
                candidate_by_id,
                label="source asset",
            )
            existing = connection.execute(
                """
                SELECT candidate_id, proposed_citekey, identity_status,
                       citekey_status, sha256, byte_size, root_alias,
                       relative_path, rights_status, asset_status
                FROM candidate_source_assets
                WHERE candidate_id = ? AND sha256 = ?
                """,
                (asset.candidate_id, asset.sha256),
            ).fetchone()
            if existing is not None and tuple(existing) != values:
                raise CatalogConflictError(
                    f"source asset {asset.candidate_id} / {asset.sha256} "
                    "conflicts with existing evidence"
                )
            yield
            if existing is None:
                self._insert_exact(
                    connection,
                    table="candidate_source_assets",
                    columns=columns,
                    values=values,
                    key_columns=("candidate_id", "sha256"),
                    key_values=(asset.candidate_id, asset.sha256),
                    label=(
                        f"source asset {asset.candidate_id} / {asset.sha256}"
                    ),
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

    def read_source_assets(
        self, *, max_records: int | None = None
    ) -> tuple[SourceAssetRecord, ...]:
        if max_records is not None and (
            type(max_records) is not int or max_records < 1
        ):
            raise ValueError("max_records must be a positive integer")
        with self._read_transaction() as connection:
            self._require_current_schema(connection)
            query = """
                SELECT candidate_id, proposed_citekey, identity_status,
                       citekey_status, sha256, byte_size, root_alias,
                       relative_path, rights_status, asset_status
                FROM candidate_source_assets
                ORDER BY candidate_id, sha256
            """
            if max_records is None:
                rows = connection.execute(query).fetchall()
            else:
                rows = connection.execute(
                    query + " LIMIT ?", (max_records + 1,)
                ).fetchall()
                if len(rows) > max_records:
                    raise CatalogSchemaError(
                        "catalog source assets exceed the requested limit"
                    )
            return tuple(
                self._source_asset_from_row(
                    tuple(row), label="candidate source asset"
                )
                for row in rows
            )

    def import_review_records(
        self,
        technical_records: Iterable[TechnicalReviewRecord],
        human_decisions: Iterable[HumanReviewDecision],
    ) -> None:
        """Append a complete valid review transition batch atomically."""
        technical_values, human_values = _bounded_review_inputs(
            technical_records,
            human_decisions,
        )
        if any(
            not isinstance(item, TechnicalReviewRecord)
            for item in technical_values
        ):
            raise TypeError(
                "technical_records must contain TechnicalReviewRecord values"
            )
        if any(
            not isinstance(item, HumanReviewDecision) for item in human_values
        ):
            raise TypeError(
                "human_decisions must contain HumanReviewDecision values"
            )
        technical_values = tuple(
            TechnicalReviewRecord.from_json(item.to_json())
            for item in technical_values
        )
        human_values = tuple(
            HumanReviewDecision.from_json(item.to_json())
            for item in human_values
        )
        with self._write_transaction() as connection:
            existing = self._read_review_projection(connection)
            technical_by_id = {
                item.record_id: item for item in existing.technical_history
            }
            for item in technical_values:
                old = technical_by_id.get(item.record_id)
                if old is not None and old != item:
                    raise CatalogConflictError(
                        f"technical review {item.record_id} conflicts with "
                        "existing evidence"
                    )
                technical_by_id[item.record_id] = item
            human_by_id = {
                decision.decision_id: decision
                for decision in existing.human_decision_history
            }
            for decision in human_values:
                previous = human_by_id.get(decision.decision_id)
                if previous is not None and previous != decision:
                    raise CatalogConflictError(
                        f"human review {decision.decision_id} conflicts with "
                        "existing evidence"
                    )
                human_by_id[decision.decision_id] = decision
            try:
                replayed = replay_review_records(
                    tuple(technical_by_id.values()),
                    tuple(human_by_id.values()),
                )
            except ReviewRecordError as error:
                raise CatalogConflictError(
                    f"review transition batch conflicts: {error}"
                ) from error
            for record in replayed.technical_history:
                self._insert_exact(
                    connection,
                    table="technical_review_records",
                    columns=_TECHNICAL_REVIEW_COLUMNS,
                    values=_technical_review_values(record),
                    key_columns=("record_id",),
                    key_values=(record.record_id,),
                    label=f"technical review {record.record_id}",
                )
            for decision in replayed.human_decision_history:
                self._insert_exact(
                    connection,
                    table="human_review_decisions",
                    columns=_HUMAN_REVIEW_COLUMNS,
                    values=_human_review_values(decision),
                    key_columns=("decision_id",),
                    key_values=(decision.decision_id,),
                    label=f"human review {decision.decision_id}",
                )
            self._validate_review_rows(connection)

    def read_review_projection(self) -> ReviewProjection:
        with self._read_transaction() as connection:
            self._require_current_schema(connection)
            return self._read_review_projection(connection)

    def export_review_json(self) -> str:
        return self.read_review_projection().to_json()

    def import_state_projections(
        self,
        projections: Iterable[ReferenceStateProjection],
    ) -> None:
        """Append reproducible cache rows after exact replay checks."""
        values = _bounded_state_projection_inputs(
            projections,
            max_projections=_MAX_STATE_PROJECTIONS,
            max_json_bytes=_MAX_STATE_PROJECTION_JSON_BYTES,
        )
        reparsed = tuple(
            ReferenceStateProjection.from_json(item.to_json())
            for item in values
        )
        by_id = {item.projection_id: item for item in reparsed}
        if len(by_id) != len(reparsed):
            raise CatalogConflictError(
                "state projection batch contains duplicate identities"
            )
        with self._write_transaction() as connection:
            stored_stats = connection.execute(
                """
                SELECT COUNT(*),
                       COALESCE(
                           SUM(length(CAST(projection_json AS BLOB))), 0
                       )
                FROM reference_state_projections
                """
            ).fetchone()
            if (
                stored_stats is None
                or type(stored_stats[0]) is not int
                or type(stored_stats[1]) is not int
            ):
                raise CatalogSchemaError(
                    "catalog state projection bounds are invalid"
                )
            if stored_stats[0] > _MAX_STATE_PROJECTIONS:
                raise CatalogSchemaError(
                    "catalog state projections exceed the record limit"
                )
            if stored_stats[1] > _MAX_STATE_PROJECTION_JSON_BYTES:
                raise CatalogSchemaError(
                    "catalog state projections exceed the JSON byte limit"
                )
            stored_rows = connection.execute(
                """
                SELECT projection_id,
                       length(CAST(projection_json AS BLOB))
                FROM reference_state_projections
                """
            ).fetchall()
            stored_ids = {str(row[0]) for row in stored_rows}
            stored_bytes = sum(int(row[1]) for row in stored_rows)
            added = tuple(
                item
                for item in reparsed
                if item.projection_id not in stored_ids
            )
            if len(stored_rows) + len(added) > _MAX_STATE_PROJECTIONS:
                raise CatalogSchemaError(
                    "catalog state projections exceed the record limit"
                )
            aggregate_bytes = stored_bytes + sum(
                len(item.to_json().encode("utf-8")) for item in added
            )
            if aggregate_bytes > _MAX_STATE_PROJECTION_JSON_BYTES:
                raise CatalogSchemaError(
                    "catalog state projections exceed the JSON byte limit"
                )
            candidate_ids = {
                str(row[0])
                for row in connection.execute(
                    "SELECT candidate_id FROM reference_candidates"
                ).fetchall()
            }
            missing = sorted(
                {item.subject_id for item in reparsed} - candidate_ids
            )
            if missing:
                raise CatalogConflictError(
                    "state projection subjects have no catalog candidates: "
                    f"{missing}"
                )
            for projection_id, projection in sorted(by_id.items()):
                self._insert_exact(
                    connection,
                    table="reference_state_projections",
                    columns=_STATE_PROJECTION_COLUMNS,
                    values=_state_projection_values(projection),
                    key_columns=("projection_id",),
                    key_values=(projection.projection_id,),
                    label=f"reference state projection {projection_id}",
                )
            self._validate_state_projection_rows(connection)

    def read_state_projections(
        self,
    ) -> tuple[ReferenceStateProjection, ...]:
        with self._read_transaction() as connection:
            self._require_current_schema(connection)
            return self._read_state_projections(
                connection,
                max_projections=_MAX_STATE_PROJECTIONS,
                max_json_bytes=_MAX_STATE_PROJECTION_JSON_BYTES,
            )

    def export_state_projections_json(self) -> str:
        projections = self.read_state_projections()
        input_ids = sorted(
            {
                input_id
                for projection in projections
                for input_id in projection.authoritative_input_ids
            }
        )
        result = (
            json.dumps(
                {
                    "artifact_kind": (
                        "projectkoios.references.catalog-state-projection"
                    ),
                    "authority_boundary": _AUTHORITY_BOUNDARY,
                    "catalog_schema_fingerprint": CATALOG_SCHEMA_FINGERPRINT,
                    "catalog_schema_version": CATALOG_SCHEMA_VERSION,
                    "authoritative_input_ids": input_ids,
                    "projections": [
                        json.loads(item.to_json()) for item in projections
                    ],
                    "exact_replay": True,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        if len(result.encode("utf-8")) > _MAX_STATE_PROJECTION_EXPORT_BYTES:
            raise CatalogSchemaError(
                "catalog state projection export exceeds its byte limit"
            )
        return result

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
            ("technical_review_records", "technical_review_records"),
            ("human_review_decisions", "human_review_decisions"),
            ("state_projections", "reference_state_projections"),
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
            self._validate_review_rows(connection)
            self._validate_state_projection_rows(connection)
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
