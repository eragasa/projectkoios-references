from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import final

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
)
from projectkoios.references.citations import CitationTargetSnapshot
from projectkoios.references.coverage import (
    CoverageAccessState,
    CoverageObservation,
    CoverageState,
)
from projectkoios.references.pdf_corpus import (
    PdfCorpusDiscoveryPlan,
    PdfSourceObservation,
)

from ._contract import (
    CITATION_DOCUMENT_MAX_DOCUMENTS_PER_KEY,
    stable_id,
)
from .document import (
    CitationSourceDocumentDescriptor,
    CitationSourceDocumentObservation,
)

CITATION_DOCUMENT_AVAILABILITY_EVALUATOR_NAME = (
    "projectkoios-references-citation-document-availability-evaluator"
)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class CitationDocumentAvailabilityEvaluationRequest(DataObjectActionRequest):
    """Cross-validate exact target, discovery, and coverage evidence."""

    target_snapshot: CitationTargetSnapshot
    discovery_plan: PdfCorpusDiscoveryPlan
    coverage_observation: CoverageObservation
    request_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.target_snapshot) is not CitationTargetSnapshot:
            raise TypeError(
                "availability target must be CitationTargetSnapshot"
            )
        self.target_snapshot.validate_identity()
        if type(self.discovery_plan) is not PdfCorpusDiscoveryPlan:
            raise TypeError(
                "availability discovery_plan must be PdfCorpusDiscoveryPlan"
            )
        if (
            PdfCorpusDiscoveryPlan.from_json(self.discovery_plan.to_json())
            != self.discovery_plan
        ):
            raise ValueError("availability discovery plan does not replay")
        if type(self.coverage_observation) is not CoverageObservation:
            raise TypeError("availability coverage must be CoverageObservation")
        if (
            CoverageObservation.from_json(self.coverage_observation.to_json())
            != self.coverage_observation
        ):
            raise ValueError("availability coverage does not replay")
        plan_roots = tuple(
            item.root_alias for item in self.discovery_plan.root_preflights
        )
        if plan_roots != self.coverage_observation.authorized_root_aliases:
            raise ValueError("availability plan and coverage roots differ")
        target_keys = tuple(item.key for item in self.target_snapshot.groups)
        coverage_keys = tuple(
            item.citekey for item in self.coverage_observation.references
        )
        if coverage_keys != target_keys:
            raise ValueError(
                "availability coverage must contain every target key once"
            )
        self._validate_candidates()
        object.__setattr__(
            self,
            "request_id",
            stable_id(
                "citation-document-availability-evaluation-request",
                {
                    "target_projection_id": (
                        self.target_snapshot.target_projection_id
                    ),
                    "discovery_plan_id": self.discovery_plan.plan_id,
                    "coverage_id": self.coverage_observation.coverage_id,
                    "policy": "exact-plan-coverage-cross-validation",
                },
            ),
        )

    def _validate_candidates(self) -> None:
        source_by_location = {
            (item.root_alias, item.relative_path): item
            for item in self.discovery_plan.source_observations
        }
        for reference in self.coverage_observation.references:
            if (
                reference.candidates
                and self.discovery_plan.plan_id not in reference.evidence
            ):
                raise ValueError(
                    "availability candidate lacks discovery-plan evidence"
                )
            for candidate in reference.candidates:
                source = source_by_location.get(
                    (candidate.root_alias, candidate.relative_path)
                )
                if source is None:
                    raise ValueError(
                        "availability candidate is absent from discovery plan"
                    )
                if (
                    not source.pdf_header_valid
                    or source.sha256 != candidate.sha256
                    or source.byte_size != candidate.byte_size
                ):
                    raise ValueError(
                        "availability candidate conflicts with discovery source"
                    )
                if source.observation_id not in reference.evidence:
                    raise ValueError(
                        "candidate lacks exact plan-source evidence"
                    )

    def validate_identity(self) -> None:
        if replace(self) != self:
            raise ValueError(
                "availability evaluation request does not match replay"
            )


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class CitationDocumentAvailabilityEvaluationResult(DataObjectActionResult):
    """Sole bounded negative-authority result for source-document projection."""

    request: CitationDocumentAvailabilityEvaluationRequest
    observations: tuple[CitationSourceDocumentObservation, ...]
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.request)
            is not CitationDocumentAvailabilityEvaluationRequest
        ):
            raise TypeError("availability result request has an invalid type")
        self.request.validate_identity()
        if type(self.observations) is not tuple or any(
            type(item) is not CitationSourceDocumentObservation
            for item in self.observations
        ):
            raise TypeError("availability result observations are invalid")
        expected = _observations_for(self.request)
        if self.observations != expected:
            raise ValueError(
                "availability result does not match evaluator replay"
            )
        object.__setattr__(
            self,
            "result_id",
            stable_id(
                "citation-document-availability-evaluation-result",
                {
                    "evaluator": CITATION_DOCUMENT_AVAILABILITY_EVALUATOR_NAME,
                    "request_id": self.request.request_id,
                    "target_projection_id": (
                        self.request.target_snapshot.target_projection_id
                    ),
                    "discovery_plan_id": self.request.discovery_plan.plan_id,
                    "coverage_id": (
                        self.request.coverage_observation.coverage_id
                    ),
                    "observation_ids": [
                        item.observation_id for item in self.observations
                    ],
                },
            ),
        )

    def validate_identity(self) -> None:
        if replace(self) != self:
            raise ValueError("availability result does not match replay")

    def negative_observation_ids(self) -> tuple[str, ...]:
        return tuple(
            observation.observation_id
            for reference, observation in zip(
                self.request.coverage_observation.references,
                self.observations,
                strict=True,
            )
            if reference.no_match
            and observation.coverage_status == "complete"
            and not observation.source_documents
            and not observation.inaccessible_evidence_ids
        )


@final
class CitationDocumentAvailabilityEvaluator(
    DataObjectActionizer[
        CitationDocumentAvailabilityEvaluationRequest,
        CitationDocumentAvailabilityEvaluationResult,
    ]
):
    """Cross-validate supplied evidence without filesystem or store access."""

    __slots__ = ()

    def action(
        self,
        *,
        request: CitationDocumentAvailabilityEvaluationRequest,
    ) -> CitationDocumentAvailabilityEvaluationResult:
        if type(self) is not CitationDocumentAvailabilityEvaluator:
            raise TypeError(
                "availability evaluator has an invalid runtime type"
            )
        if type(request) is not CitationDocumentAvailabilityEvaluationRequest:
            raise TypeError("availability request has an invalid runtime type")
        request.validate_identity()
        return CitationDocumentAvailabilityEvaluationResult(
            request=request,
            observations=_observations_for(request),
        )


def _observations_for(
    request: CitationDocumentAvailabilityEvaluationRequest,
) -> tuple[CitationSourceDocumentObservation, ...]:
    source_by_location = {
        (item.root_alias, item.relative_path): item
        for item in request.discovery_plan.source_observations
    }
    global_complete = (
        request.discovery_plan.coverage_status == "complete"
        and not request.discovery_plan.skipped_observations
        and request.coverage_observation.state is CoverageState.COMPLETE
        and not request.coverage_observation.failures
        and not request.coverage_observation.exclusions
    )
    observations: list[CitationSourceDocumentObservation] = []
    for group, reference in zip(
        request.target_snapshot.groups,
        request.coverage_observation.references,
        strict=True,
    ):
        sources = tuple(
            source_by_location[(candidate.root_alias, candidate.relative_path)]
            for candidate in reference.candidates
        )
        descriptors = _descriptors(sources)
        plan_bound = request.discovery_plan.plan_id in reference.evidence
        coverage_complete = global_complete and plan_bound
        inaccessible: tuple[str, ...] = ()
        if reference.access_state is not CoverageAccessState.NONE:
            inaccessible = (
                stable_id(
                    "citation-document-availability-access-evidence",
                    {
                        "request_id": request.request_id,
                        "target_group_id": group.group_id,
                        "literal_citekey": group.key,
                        "access_state": reference.access_state.value,
                        "coverage_evidence": list(reference.evidence),
                    },
                ),
            )
        evidence_id = stable_id(
            "citation-document-availability-observation-evidence",
            {
                "request_id": request.request_id,
                "target_group_id": group.group_id,
                "literal_citekey": group.key,
                "discovery_plan_id": request.discovery_plan.plan_id,
                "coverage_id": request.coverage_observation.coverage_id,
                "coverage_evidence": list(reference.evidence),
                "source_observation_ids": [
                    item.observation_id for item in sources
                ],
                "access_state": reference.access_state.value,
                "no_match": reference.no_match,
            },
        )
        observations.append(
            CitationSourceDocumentObservation(
                target_snapshot_id=request.target_snapshot.snapshot_id,
                literal_citekey=group.key,
                coverage_status=(
                    "complete" if coverage_complete else "incomplete"
                ),
                source_documents=descriptors,
                inaccessible_evidence_ids=inaccessible,
                evidence_id=evidence_id,
            )
        )
    return tuple(observations)


def _descriptors(
    sources: tuple[PdfSourceObservation, ...],
) -> tuple[CitationSourceDocumentDescriptor, ...]:
    descriptors = tuple(
        sorted(
            (
                CitationSourceDocumentDescriptor(
                    source_document_id=item.observation_id,
                    sha256=item.sha256,
                    byte_size=item.byte_size,
                )
                for item in sources
            ),
            key=lambda item: item.descriptor_id,
        )
    )
    if len(descriptors) > CITATION_DOCUMENT_MAX_DOCUMENTS_PER_KEY:
        raise ValueError("availability documents exceed the per-key limit")
    return descriptors
