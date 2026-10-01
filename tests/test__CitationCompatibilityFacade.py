from __future__ import annotations

import warnings

import projectkoios.references.bibliography as bibliography
import projectkoios.references.citation_document as deprecated_facade
import projectkoios.references.citations as citations
import projectkoios.references.documents as documents

_CITATION_EXPORTS = (
    "CITATION_DOCUMENT_MAX_BIBLIOGRAPHY_ENTRIES",
    "CITATION_DOCUMENT_MAX_CANONICAL_PAYLOAD_BYTES",
    "CITATION_DOCUMENT_MAX_CITATION_KEY_CHARACTERS",
    "CITATION_DOCUMENT_MAX_ID_BYTES",
    "CITATION_DOCUMENT_MAX_KEYS",
    "CITATION_DOCUMENT_MAX_OCCURRENCES",
    "CITATION_DOCUMENT_MAX_SOURCE_GAPS",
    "CITATION_DOCUMENT_MAX_SOURCE_PATH_BYTES",
    "CITATION_DOCUMENT_MAX_TARGET_AGGREGATE_SOURCE_BYTES",
    "CITATION_DOCUMENT_MAX_TARGET_RECORDS",
    "CITATION_DOCUMENT_MAX_TARGET_REFERENCES_PER_RECORD",
    "CITATION_DOCUMENT_MAX_TARGET_SOURCE_BYTES",
    "CITATION_DOCUMENT_MAX_TARGET_SOURCE_FILES",
    "CITATION_DOCUMENT_MAX_TEXT_BYTES",
    "CitationContentIdentity",
    "CitationKeyResolutionStatus",
    "CitationSourceLocator",
    "CitationTargetBibliographyEntry",
    "CitationTargetGroup",
    "CitationTargetOccurrence",
    "CitationTargetSnapshot",
    "CitationTargetSourceGap",
)
_BIBLIOGRAPHY_EXPORTS = (
    "CitationBibliographyMembershipStatus",
    "CitationBibliographyObservationBinding",
)
_DOCUMENT_EXPORTS = (
    "CitationDocumentAvailabilityStatus",
    "CitationDocumentProjection",
    "CitationDocumentProjectionItem",
    "CitationDocumentProjectionRequest",
    "CitationDocumentProjectionResult",
    "CitationDocumentProjector",
    "CitationSourceDocumentDescriptor",
    "CitationSourceDocumentLink",
    "CitationSourceDocumentLinkRequest",
    "CitationSourceDocumentLinkResult",
    "CitationSourceDocumentLinker",
    "CitationSourceDocumentObservation",
)


def test__canonical_citation_and_bibliography_imports_are_warning_free() -> (
    None
):
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        assert citations.CitationTargetSnapshot.__module__ == (
            "projectkoios.references.citations.base"
        )
        assert (
            bibliography.CitationBibliographyObservationBinding.__module__
            == ("projectkoios.references.bibliography.base")
        )
        assert documents.CitationDocumentProjection.__module__ == (
            "projectkoios.references.documents.projection"
        )

    assert captured == []


def test__deprecated_exports_preserve_identity_and_warn_once() -> None:
    deprecated_facade._WARNED_DEPRECATED_EXPORTS.clear()
    expected = {
        **{name: getattr(citations, name) for name in _CITATION_EXPORTS},
        **{name: getattr(bibliography, name) for name in _BIBLIOGRAPHY_EXPORTS},
        **{name: getattr(documents, name) for name in _DOCUMENT_EXPORTS},
    }

    imported: dict[str, object] = {}
    with warnings.catch_warnings(record=True) as first_warnings:
        warnings.simplefilter("always")
        exec(
            "from projectkoios.references.citation_document "
            "import CitationTargetSnapshot as moved",
            {},
            imported,
        )
        first = {
            name: getattr(deprecated_facade, name)
            for name in (
                *_CITATION_EXPORTS,
                *_BIBLIOGRAPHY_EXPORTS,
                *_DOCUMENT_EXPORTS,
            )
        }
    with warnings.catch_warnings(record=True) as repeated_warnings:
        warnings.simplefilter("always")
        repeated = {
            name: getattr(deprecated_facade, name)
            for name in (
                *_CITATION_EXPORTS,
                *_BIBLIOGRAPHY_EXPORTS,
                *_DOCUMENT_EXPORTS,
            )
        }

    assert imported["moved"] is citations.CitationTargetSnapshot
    assert first == expected
    assert repeated == expected
    assert all(first[name] is expected[name] for name in expected)
    assert len(first_warnings) == len(expected)
    assert all(item.category is DeprecationWarning for item in first_warnings)
    assert all("is deprecated" in str(item.message) for item in first_warnings)
    assert repeated_warnings == []


def test__deprecated_submodules_preserve_exact_object_identity() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from projectkoios.references.citation_document.document import (
            CitationSourceDocumentDescriptor as OldDescriptor,
        )
        from projectkoios.references.citation_document.linkage import (
            CitationSourceDocumentLinker as OldLinker,
        )
        from projectkoios.references.citation_document.projection import (
            CitationDocumentProjector as OldProjector,
        )
        from projectkoios.references.citation_document.statuses import (
            CitationDocumentAvailabilityStatus as OldStatus,
        )

    assert OldDescriptor is documents.CitationSourceDocumentDescriptor
    assert OldLinker is documents.CitationSourceDocumentLinker
    assert OldProjector is documents.CitationDocumentProjector
    assert OldStatus is documents.CitationDocumentAvailabilityStatus
