from __future__ import annotations

import sqlite3

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
from projectkoios.references.io_limits import REVIEW_IO_LIMITS
from projectkoios.references.models import SourceAssetRecord
from projectkoios.references.review import (
    HumanReviewDecision,
    ReviewProjection,
    ReviewRecordError,
    TechnicalReviewRecord,
    replay_review_records,
)
from projectkoios.references.state_projection import (
    ReferenceStateProjection,
    StateProjectionError,
)

from .schema import (
    _MAX_STATE_PROJECTION_JSON_BYTES,
    _MAX_STATE_PROJECTIONS,
    CatalogSchemaError,
)
from .serialization import (
    _asset_values,
    _candidate_values,
    _graph_candidate_values,
    _graph_edge_values,
    _graph_source_values,
    _human_review_values,
    _observation_values,
    _state_projection_values,
    _technical_review_values,
)


class _CatalogReplayInternals:
    """Private canonical replay and persisted-row validation internals."""

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

    def _read_review_projection(
        self, connection: sqlite3.Connection
    ) -> ReviewProjection:
        self._preflight_review_rows(connection)
        technical_rows = connection.execute(
            """
            SELECT record_id, record_schema_version, authority_kind,
                   producer_name, producer_version, effective_limits_id,
                   subject_id, context_id, technical_kind, outcome,
                   transition_kind, actor_id, actor_kind, authority_scope,
                   authority_domain, verification_record_id, observed_at,
                   supersedes_record_id, record_json
            FROM technical_review_records
            ORDER BY record_id
            """
        )
        technical: list[TechnicalReviewRecord] = []
        for row in technical_rows:
            try:
                record = TechnicalReviewRecord.from_json(str(row[18]))
            except ValueError as error:
                raise CatalogSchemaError(
                    f"technical review row {row[0]} has invalid canonical JSON"
                ) from error
            if tuple(row) != _technical_review_values(record):
                raise CatalogSchemaError(
                    f"technical review row {row[0]} differs from canonical JSON"
                )
            technical.append(record)

        human_rows = connection.execute(
            """
            SELECT decision_id, record_schema_version, authority_kind,
                   producer_name, producer_version, effective_limits_id,
                   subject_id, context_id, dimension, decision,
                   transition_kind, actor_id, actor_kind, authority_scope,
                   authority_domain, verification_record_id, decided_at,
                   supersedes_decision_id, decision_json
            FROM human_review_decisions
            ORDER BY decision_id
            """
        )
        decisions: list[HumanReviewDecision] = []
        for row in human_rows:
            try:
                decision = HumanReviewDecision.from_json(str(row[18]))
            except ValueError as error:
                raise CatalogSchemaError(
                    f"human review row {row[0]} has invalid canonical JSON"
                ) from error
            if tuple(row) != _human_review_values(decision):
                raise CatalogSchemaError(
                    f"human review row {row[0]} differs from canonical JSON"
                )
            decisions.append(decision)
        try:
            return replay_review_records(tuple(technical), tuple(decisions))
        except ReviewRecordError as error:
            raise CatalogSchemaError(
                f"catalog review history is invalid: {error}"
            ) from error

    @staticmethod
    def _preflight_review_rows(connection: sqlite3.Connection) -> None:
        maximum_entries = REVIEW_IO_LIMITS.max_entries
        maximum_json_bytes = REVIEW_IO_LIMITS.max_json_bytes
        if maximum_entries is None or maximum_json_bytes is None:
            raise RuntimeError("review limits omit catalog preflight ceilings")
        counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM technical_review_records),
                (SELECT COUNT(*) FROM human_review_decisions)
            """
        ).fetchone()
        if counts is None or any(type(value) is not int for value in counts):
            raise CatalogSchemaError("catalog review counts are invalid")
        total_entries = counts[0] + counts[1]
        if total_entries > maximum_entries:
            raise CatalogSchemaError(
                "catalog review history exceeds the record limit: "
                f"observed {total_entries}, limit {maximum_entries}"
            )
        byte_counts = connection.execute(
            """
            SELECT
                (SELECT COALESCE(
                    SUM(length(CAST(record_json AS BLOB))), 0
                ) FROM technical_review_records),
                (SELECT COALESCE(
                    SUM(length(CAST(decision_json AS BLOB))), 0
                ) FROM human_review_decisions)
            """
        ).fetchone()
        if byte_counts is None or any(
            type(value) is not int for value in byte_counts
        ):
            raise CatalogSchemaError("catalog review JSON sizes are invalid")
        total_json_bytes = byte_counts[0] + byte_counts[1]
        if total_json_bytes > maximum_json_bytes:
            raise CatalogSchemaError(
                "catalog review history exceeds the JSON byte limit: "
                f"observed {total_json_bytes}, limit {maximum_json_bytes}"
            )

    def _validate_review_rows(self, connection: sqlite3.Connection) -> None:
        self._read_review_projection(connection)

    def _read_state_projections(
        self,
        connection: sqlite3.Connection,
        *,
        max_projections: int = _MAX_STATE_PROJECTIONS,
        max_json_bytes: int = _MAX_STATE_PROJECTION_JSON_BYTES,
    ) -> tuple[ReferenceStateProjection, ...]:
        stats = connection.execute(
            """
            SELECT COUNT(*),
                   COALESCE(SUM(length(CAST(projection_json AS BLOB))), 0)
            FROM reference_state_projections
            """
        ).fetchone()
        if (
            stats is None
            or type(stats[0]) is not int
            or type(stats[1]) is not int
        ):
            raise CatalogSchemaError(
                "catalog state projection bounds are invalid"
            )
        if stats[0] > max_projections:
            raise CatalogSchemaError(
                "catalog state projections exceed the record limit"
            )
        if stats[1] > max_json_bytes:
            raise CatalogSchemaError(
                "catalog state projections exceed the JSON byte limit"
            )
        rows = connection.execute(
            """
            SELECT projection_id, record_schema_version, artifact_kind,
                   subject_id, authoritative_input_ids_json, projection_json
            FROM reference_state_projections
            ORDER BY projection_id
            """
        ).fetchall()
        candidate_ids = {
            str(row[0])
            for row in connection.execute(
                "SELECT candidate_id FROM reference_candidates"
            ).fetchall()
        }
        result: list[ReferenceStateProjection] = []
        for row in rows:
            try:
                projection = ReferenceStateProjection.from_json(str(row[5]))
            except StateProjectionError as error:
                raise CatalogSchemaError(
                    f"state projection row {row[0]} has invalid canonical JSON"
                ) from error
            if tuple(row) != _state_projection_values(projection):
                raise CatalogSchemaError(
                    f"state projection row {row[0]} differs from canonical JSON"
                )
            if projection.subject_id not in candidate_ids:
                raise CatalogSchemaError(
                    f"state projection row {row[0]} has no catalog candidate"
                )
            result.append(projection)
        return tuple(result)

    def _validate_state_projection_rows(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        self._read_state_projections(connection)

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
