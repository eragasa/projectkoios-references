from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import final
from urllib.parse import urlparse

from projectkoios.base import DataObjectModel
from projectkoios.references.assets import AssetDiscoveryPlan
from projectkoios.references.citation_closure import (
    CitationClosure,
)
from projectkoios.references.coverage import (
    CoverageAccessState,
    CoverageObservation,
    CoverageState,
    ReferenceCoverage,
)
from projectkoios.references.identity import ReferenceCandidate
from projectkoios.references.path_safety import (
    PlaceholderObservation,
    PlaceholderStatus,
    validate_citekey,
)

from ._contract import (
    _EXPECTED_PDF_TYPES,
)
from .errors import CollectionReconciliationError
from .loading import ManagedPdf


class PdfExpectation(StrEnum):
    EXPECTED = "expected"
    REVIEW = "review"
    NOT_APPLICABLE = "not-applicable"


class PdfStatus(StrEnum):
    MANAGED_VERIFIED = "managed-verified"
    MANAGED_PRESENT = "managed-present"
    LOCATED_UNVERIFIED = "located-unverified"
    AMBIGUOUS_MATCHES = "ambiguous-matches"
    ALTERNATE_VERSION_ONLY = "alternate-version-only"
    CLOUD_PLACEHOLDER = "cloud-placeholder"
    NOT_YET_SEARCHED = "not-yet-searched"
    SEARCH_INCOMPLETE = "search-incomplete"
    SEARCH_FAILED = "search-failed"
    NOT_LOCATED = "not-located"
    ACCESS_CONTROLLED = "access-controlled"
    FULL_TEXT_NOT_PUBLIC = "full-text-not-public"
    PDF_NOT_APPLICABLE = "pdf-not-applicable"
    PDF_APPLICABILITY_REVIEW = "pdf-applicability-review"


class CitationStatus(StrEnum):
    CITED_DEFINED = "cited-defined"
    DEFINED_UNCITED = "defined-uncited"
    CLOSURE_UNAVAILABLE = "closure-unavailable"


@final
@dataclass(frozen=True)
class CollectionReference(DataObjectModel):
    proposed_citekey: str
    identity_status: str
    citekey_status: str
    entry_type: str
    source_type: str
    full_text_expected: bool | None
    title: str | None
    year: str | None
    doi: str | None
    source_bibliographies: tuple[str, ...]
    metadata_verification_status: str
    reading_status: str
    reading_decision_status: str
    citation_status: CitationStatus
    pdf_expectation: PdfExpectation
    pdf_status: PdfStatus
    managed_pdf: str | None
    sha256: str | None
    byte_size: int | None
    discovery_evidence: tuple[str, ...]
    duplicate_citekeys: tuple[str, ...]
    acquisition_status: str
    access_status: str
    rights_status: str
    ingestion_status: str
    transcript_status: str
    state_projection_id: str
    state_discrepancy_fields: tuple[str, ...]
    next_lawful_action: str

    def __post_init__(self) -> None:
        validate_citekey(
            self.proposed_citekey,
            field="proposed citekey",
        )
        if self.identity_status != "unaccepted-candidate":
            raise ValueError(
                "collection reference cannot claim accepted identity"
            )
        if self.citekey_status != "proposed-noncanonical":
            raise ValueError(
                "collection reference citekey must be noncanonical"
            )


@final
@dataclass(frozen=True)
class ExtraPdf(DataObjectModel):
    filename: str
    proposed_citekey: str
    sha256: str
    byte_size: int
    duplicate_citekeys: tuple[str, ...]
    access_status: str
    rights_status: str
    ingestion_status: str
    transcript_status: str


def _classify_pdf_status(
    *,
    matched_pdf: ManagedPdf | None,
    expectation: PdfExpectation,
    observation: CoverageObservation | None,
    evidence: ReferenceCoverage | None,
    preflight: PlaceholderObservation | None = None,
) -> tuple[PdfStatus, str]:
    if matched_pdf is not None:
        return (
            (
                PdfStatus.MANAGED_VERIFIED
                if matched_pdf.historically_verified
                else PdfStatus.MANAGED_PRESENT
            ),
            (
                "verify-bibliographic-metadata-and-rights"
                if matched_pdf.historically_verified
                else "review-pdf-identity-rights-and-record-acquisition"
            ),
        )
    if preflight is not None:
        if preflight.status is PlaceholderStatus.CLOUD_PLACEHOLDER:
            return (
                PdfStatus.CLOUD_PLACEHOLDER,
                "request-explicit-placeholder-hydration-authorization",
            )
        if preflight.status in {
            PlaceholderStatus.ACCESS_CONTROLLED,
            PlaceholderStatus.UNREADABLE,
        }:
            return (
                PdfStatus.ACCESS_CONTROLLED,
                "resolve-local-file-access-without-bypassing-controls",
            )
        raise CollectionReconciliationError(
            "managed-root preflight has unsupported result"
        )
    if expectation is PdfExpectation.NOT_APPLICABLE:
        if evidence is not None and (
            evidence.candidates
            or evidence.access_state is not CoverageAccessState.NONE
        ):
            return (
                PdfStatus.PDF_APPLICABILITY_REVIEW,
                "resolve-source-type-and-pdf-applicability-conflict",
            )
        return (
            PdfStatus.PDF_NOT_APPLICABLE,
            "verify-non-pdf-source-locator",
        )
    if expectation is PdfExpectation.REVIEW:
        return (
            PdfStatus.PDF_APPLICABILITY_REVIEW,
            "decide-whether-a-pdf-is-applicable",
        )
    if evidence is None or observation is None:
        return (
            PdfStatus.NOT_YET_SEARCHED,
            "supply-typed-coverage-or-search-authorized-roots",
        )
    if evidence.access_state is CoverageAccessState.CLOUD_PLACEHOLDER:
        return (
            PdfStatus.CLOUD_PLACEHOLDER,
            "request-explicit-placeholder-hydration-authorization",
        )
    if evidence.access_state is CoverageAccessState.ACCESS_CONTROLLED:
        return (
            PdfStatus.ACCESS_CONTROLLED,
            "record-lawful-access-path-without-bypassing-controls",
        )
    if evidence.access_state is CoverageAccessState.FULL_TEXT_NOT_PUBLIC:
        return (
            PdfStatus.FULL_TEXT_NOT_PUBLIC,
            "record-public-metadata-and-private-access-limits",
        )
    if evidence.candidates:
        if evidence.competing_content_count > 1:
            return (
                PdfStatus.AMBIGUOUS_MATCHES,
                "review-competing-candidate-identities",
            )
        if evidence.competing_content_count == 1:
            return (
                PdfStatus.LOCATED_UNVERIFIED,
                "verify-candidate-identity-rights-and-version",
            )
        if evidence.alternate_content_count:
            return (
                PdfStatus.ALTERNATE_VERSION_ONLY,
                "review-alternate-version-identity-and-rights",
            )
        raise CollectionReconciliationError(
            "coverage candidates have no classifiable content identity"
        )
    if not evidence.no_match:
        raise CollectionReconciliationError(
            "coverage evidence has no classifiable outcome"
        )
    if observation.state is CoverageState.COMPLETE:
        return (
            PdfStatus.NOT_LOCATED,
            "record-completed-coverage-or-authorize-new-roots",
        )
    if observation.state is CoverageState.INCOMPLETE:
        return (
            PdfStatus.SEARCH_INCOMPLETE,
            "complete-or-supersede-the-bounded-search",
        )
    if observation.state is CoverageState.FAILED:
        return (
            PdfStatus.SEARCH_FAILED,
            "resolve-recorded-search-failure-before-absence-claim",
        )
    return (
        PdfStatus.NOT_YET_SEARCHED,
        "search-explicitly-authorized-roots",
    )


def _classify_asset_plan_status(
    *,
    candidate_id: str,
    asset_plan: AssetDiscoveryPlan,
    fallback: tuple[PdfStatus, str],
) -> tuple[PdfStatus, str]:
    ambiguity = asset_plan.ambiguity_status(candidate_id)
    if fallback[0] not in {
        PdfStatus.NOT_YET_SEARCHED,
        PdfStatus.NOT_LOCATED,
        PdfStatus.SEARCH_INCOMPLETE,
        PdfStatus.SEARCH_FAILED,
    }:
        if ambiguity != "unresolved-single-heuristic-candidate":
            return (
                PdfStatus.AMBIGUOUS_MATCHES,
                "review-all-heuristic-candidates-versions-and-record-rejections",
            )
        return fallback
    if ambiguity == "unresolved-single-heuristic-candidate":
        return (
            PdfStatus.LOCATED_UNVERIFIED,
            "obtain-actor-provenanced-asset-identity-authorization",
        )
    return (
        PdfStatus.AMBIGUOUS_MATCHES,
        "review-all-heuristic-candidates-versions-and-record-rejections",
    )


def _pdf_expectation(record: ReferenceCandidate) -> PdfExpectation:
    source_type = _source_type(record)
    if record.entry_type.lower() in _EXPECTED_PDF_TYPES:
        return PdfExpectation.EXPECTED
    if source_type == "preprint":
        return PdfExpectation.EXPECTED
    if source_type in {
        "manual-or-documentation",
        "software-repository",
        "website",
    }:
        return PdfExpectation.NOT_APPLICABLE
    return PdfExpectation.REVIEW


def _source_type(record: ReferenceCandidate) -> str:
    entry_type = record.entry_type.lower()
    if entry_type == "misc":
        if record.eprint or (
            record.doi is not None and record.doi.startswith("10.48550/arxiv.")
        ):
            return "preprint"
        if record.url:
            hostname = (urlparse(record.url).hostname or "").lower()
            if hostname in {"github.com", "www.github.com"}:
                return "software-repository"
            return "website"
        return "miscellaneous"
    return {
        "article": "journal-article",
        "book": "book",
        "inproceedings": "conference-paper",
        "conference": "conference-paper",
        "manual": "manual-or-documentation",
    }.get(entry_type, entry_type)


def _full_text_expected(expectation: PdfExpectation) -> bool | None:
    if expectation is PdfExpectation.EXPECTED:
        return True
    if expectation is PdfExpectation.NOT_APPLICABLE:
        return False
    return None


def _coverage_claims(
    *,
    coverage_observation: CoverageObservation | None,
    processing_supplied: bool,
    acquisition_supplied: bool,
    review_supplied: bool,
    citation_closure_supplied: bool,
) -> tuple[str, ...]:
    values = {
        "preserved-bibliography-bytes",
        "collection-row-evidence",
        "managed-pdf-directory",
        (
            "processing-evidence:supplied"
            if processing_supplied
            else "processing-evidence:not-supplied"
        ),
        (
            "acquisition-evidence:supplied"
            if acquisition_supplied
            else "acquisition-evidence:not-supplied"
        ),
        (
            "review-evidence:supplied"
            if review_supplied
            else "review-evidence:not-supplied"
        ),
        (
            "citation-closure:supplied"
            if citation_closure_supplied
            else "citation-closure:not-supplied"
        ),
    }
    if processing_supplied:
        values.update(
            {
                "processing-contract:proposed",
                "processing-audit:recorded-producer-status",
                "processing-independent-revalidation:not-performed",
            }
        )
    if coverage_observation is None:
        values.update(
            {
                "pdf-coverage:not-supplied",
                "ambiguity:not-evaluated",
            }
        )
    else:
        values.update(
            {
                f"pdf-coverage:{coverage_observation.state.value}",
                f"pdf-coverage-id:{coverage_observation.coverage_id}",
                "source-revision:asserted-not-verified",
                f"ambiguity:{coverage_observation.ambiguity_evaluation.value}",
                "authorized-roots:"
                + ",".join(coverage_observation.authorized_root_aliases),
                f"coverage-exclusions:{len(coverage_observation.exclusions)}",
                f"coverage-failures:{len(coverage_observation.failures)}",
            }
        )
    return tuple(sorted(values))


def _counts(
    references: tuple[CollectionReference, ...],
    extras: tuple[ExtraPdf, ...],
    citation_closure: CitationClosure | None,
) -> dict[str, int]:
    counts = {
        "references": len(references),
        "managed_pdfs": sum(
            record.managed_pdf is not None for record in references
        ),
        "missing_expected_pdfs": sum(
            record.pdf_expectation is PdfExpectation.EXPECTED
            and record.managed_pdf is None
            for record in references
        ),
        "not_yet_searched": sum(
            record.pdf_status is PdfStatus.NOT_YET_SEARCHED
            for record in references
        ),
        "search_incomplete": sum(
            record.pdf_status is PdfStatus.SEARCH_INCOMPLETE
            for record in references
        ),
        "search_failed": sum(
            record.pdf_status is PdfStatus.SEARCH_FAILED
            for record in references
        ),
        "not_located": sum(
            record.pdf_status is PdfStatus.NOT_LOCATED for record in references
        ),
        "located_unverified": sum(
            record.pdf_status is PdfStatus.LOCATED_UNVERIFIED
            for record in references
        ),
        "ambiguous_matches": sum(
            record.pdf_status is PdfStatus.AMBIGUOUS_MATCHES
            for record in references
        ),
        "alternate_version_only": sum(
            record.pdf_status is PdfStatus.ALTERNATE_VERSION_ONLY
            for record in references
        ),
        "cloud_placeholders": sum(
            record.pdf_status is PdfStatus.CLOUD_PLACEHOLDER
            for record in references
        ),
        "access_controlled": sum(
            record.pdf_status is PdfStatus.ACCESS_CONTROLLED
            for record in references
        ),
        "full_text_not_public": sum(
            record.pdf_status is PdfStatus.FULL_TEXT_NOT_PUBLIC
            for record in references
        ),
        "pdf_applicability_review": sum(
            record.pdf_status is PdfStatus.PDF_APPLICABILITY_REVIEW
            for record in references
        ),
        "pdf_not_applicable": sum(
            record.pdf_status is PdfStatus.PDF_NOT_APPLICABLE
            for record in references
        ),
        "extra_pdfs": len(extras),
        "seed_raw_extractions": sum(
            record.ingestion_status
            == "completed-source-bound-reference-evidence"
            for record in references
        ),
        "seed_transcripts_with_recorded_passing_audit": sum(
            record.transcript_status
            == "automated-unreviewed-with-recorded-passing-audit"
            for record in references
        ),
        "extra_raw_extractions": sum(
            extra.ingestion_status
            == "completed-source-bound-reference-evidence"
            for extra in extras
        ),
        "extra_transcripts_with_recorded_passing_audit": sum(
            extra.transcript_status
            == "automated-unreviewed-with-recorded-passing-audit"
            for extra in extras
        ),
        "duplicate_content_groups": len(
            {
                tuple(
                    sorted(
                        (
                            record.proposed_citekey,
                            *record.duplicate_citekeys,
                        )
                    )
                )
                for record in references
                if record.duplicate_citekeys
            }
        ),
        "cited_and_defined": 0,
        "cited_but_undefined": 0,
        "defined_but_uncited": 0,
    }
    if citation_closure is not None:
        counts.update(
            {
                "cited_and_defined": len(citation_closure.cited_and_defined),
                "cited_but_undefined": len(
                    citation_closure.cited_but_undefined
                ),
                "defined_but_uncited": len(
                    citation_closure.defined_but_uncited
                ),
            }
        )
    return counts
