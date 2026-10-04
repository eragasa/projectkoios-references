from __future__ import annotations

import json
from collections.abc import Iterable
from itertools import islice

from projectkoios.references.graph import (
    CitationCandidate,
    CitationEdge,
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
    ReviewRecordError,
    TechnicalReviewRecord,
)
from projectkoios.references.state_projection import (
    ReferenceStateProjection,
)

from .schema import (
    _MAX_STATE_PROJECTION_JSON_BYTES,
    _MAX_STATE_PROJECTIONS,
    CatalogSchemaError,
)


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


def _technical_review_values(
    record: TechnicalReviewRecord,
) -> tuple[object, ...]:
    return (
        record.record_id,
        record.schema_version,
        record.authority_kind,
        record.producer.name,
        record.producer.version,
        record.effective_limits_id,
        record.subject_id,
        record.context_id,
        record.technical_kind.value,
        record.outcome.value,
        record.transition_kind.value,
        record.actor.actor_id,
        record.actor.actor_kind.value,
        record.actor.authority_scope.value,
        record.actor.authority_domain,
        record.actor.verification_record_id,
        record.observed_at,
        record.supersedes_record_id,
        record.to_json(),
    )


def _human_review_values(
    decision: HumanReviewDecision,
) -> tuple[object, ...]:
    return (
        decision.decision_id,
        decision.schema_version,
        decision.authority_kind,
        decision.producer.name,
        decision.producer.version,
        decision.effective_limits_id,
        decision.subject_id,
        decision.context_id,
        decision.dimension.value,
        decision.decision,
        decision.transition_kind.value,
        decision.actor.actor_id,
        decision.actor.actor_kind.value,
        decision.actor.authority_scope.value,
        decision.actor.authority_domain,
        decision.actor.verification_record_id,
        decision.decided_at,
        decision.supersedes_decision_id,
        decision.to_json(),
    )


def _state_projection_values(
    projection: ReferenceStateProjection,
) -> tuple[object, ...]:
    return (
        projection.projection_id,
        projection.schema_version,
        projection.artifact_kind,
        projection.subject_id,
        _compact_json(projection.authoritative_input_ids),
        projection.to_json(),
    )


def _bounded_state_projection_inputs(
    projections: Iterable[ReferenceStateProjection],
    *,
    max_projections: int = _MAX_STATE_PROJECTIONS,
    max_json_bytes: int = _MAX_STATE_PROJECTION_JSON_BYTES,
) -> tuple[ReferenceStateProjection, ...]:
    values = tuple(islice(iter(projections), max_projections + 1))
    if len(values) > max_projections:
        raise CatalogSchemaError(
            "state projection batch exceeds the record limit"
        )
    if any(not isinstance(item, ReferenceStateProjection) for item in values):
        raise TypeError(
            "projections must contain ReferenceStateProjection values"
        )
    total_bytes = sum(len(item.to_json().encode("utf-8")) for item in values)
    if total_bytes > max_json_bytes:
        raise CatalogSchemaError(
            "state projection batch exceeds the JSON byte limit"
        )
    return values


def _bounded_review_inputs(
    technical_records: Iterable[TechnicalReviewRecord],
    human_decisions: Iterable[HumanReviewDecision],
) -> tuple[tuple[TechnicalReviewRecord, ...], tuple[HumanReviewDecision, ...]]:
    maximum = REVIEW_IO_LIMITS.max_entries
    if maximum is None:  # pragma: no cover - fixed profile invariant
        raise RuntimeError("review limits omit the record ceiling")
    technical_values = tuple(islice(iter(technical_records), maximum + 1))
    if len(technical_values) > maximum:
        raise ReviewRecordError("review import exceeds the record limit")
    remaining = maximum - len(technical_values)
    human_values = tuple(islice(iter(human_decisions), remaining + 1))
    if len(human_values) > remaining:
        raise ReviewRecordError("review import exceeds the record limit")
    return technical_values, human_values


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

_TECHNICAL_REVIEW_COLUMNS = (
    "record_id",
    "record_schema_version",
    "authority_kind",
    "producer_name",
    "producer_version",
    "effective_limits_id",
    "subject_id",
    "context_id",
    "technical_kind",
    "outcome",
    "transition_kind",
    "actor_id",
    "actor_kind",
    "authority_scope",
    "authority_domain",
    "verification_record_id",
    "observed_at",
    "supersedes_record_id",
    "record_json",
)

_STATE_PROJECTION_COLUMNS = (
    "projection_id",
    "record_schema_version",
    "artifact_kind",
    "subject_id",
    "authoritative_input_ids_json",
    "projection_json",
)

_HUMAN_REVIEW_COLUMNS = (
    "decision_id",
    "record_schema_version",
    "authority_kind",
    "producer_name",
    "producer_version",
    "effective_limits_id",
    "subject_id",
    "context_id",
    "dimension",
    "decision",
    "transition_kind",
    "actor_id",
    "actor_kind",
    "authority_scope",
    "authority_domain",
    "verification_record_id",
    "decided_at",
    "supersedes_decision_id",
    "decision_json",
)
