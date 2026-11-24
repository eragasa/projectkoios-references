from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, fields

import pytest
from projectkoios.references.bibliography import (
    CitationBibliographyObservationBinding,
)
from projectkoios.references.citations import (
    CitationContentIdentity,
    CitationSourceLocator,
    CitationTargetBibliographyEntry,
)
from projectkoios.references.identity import (
    ProducerIdentity,
    SourceBibliographyObservation,
)

_ENTRY = "@article{exactKey, title={Exact Entry}}"
_BIBLIOGRAPHY = (_ENTRY + "\n").encode()


def _content(value: bytes) -> CitationContentIdentity:
    return CitationContentIdentity(
        algorithm="sha256",
        digest=hashlib.sha256(value).hexdigest(),
        byte_count=len(value),
    )


def _entry() -> CitationTargetBibliographyEntry:
    source_identity = _content(_BIBLIOGRAPHY)
    return CitationTargetBibliographyEntry(
        entry_id="citation-entry:" + "a" * 64,
        entry_index=0,
        key="exactKey",
        entry_type="article",
        locator=CitationSourceLocator(
            source_path="references.bib",
            source_content_identity=source_identity,
            include_index=0,
            byte_start=0,
            byte_end=len(_BIBLIOGRAPHY),
            line=1,
            column=1,
        ),
        entry_content_identity=_content(_ENTRY.encode()),
    )


def _observation() -> SourceBibliographyObservation:
    return SourceBibliographyObservation.create(
        source_id="source:bibliography",
        asserted_source_revision="revision:exact",
        source_path="references.bib",
        bibliography_bytes=_BIBLIOGRAPHY,
        entry_index=0,
        observed_citekey="exactKey",
        verbatim_entry=_ENTRY,
        parser=ProducerIdentity(name="test-parser", version="1"),
    )


def test__binding__preserves_exact_entry_and_observation() -> None:
    entry = _entry()
    observation = _observation()
    binding = CitationBibliographyObservationBinding(
        entry=entry,
        observation=observation,
    )

    binding.validate_identity()
    assert binding.entry is entry
    assert binding.observation is observation
    assert binding.binding_id.startswith(
        "citation-bibliography-binding:sha256:"
    )
    with pytest.raises(FrozenInstanceError):
        binding.entry = entry  # type: ignore[misc]


@pytest.mark.parametrize(
    "changed",
    (
        {"observed_citekey": "anotherKey"},
        {"entry_index": 1},
        {"source_path": "other.bib"},
        {"bibliography_sha256": "0" * 64},
        {"bibliography_byte_size": len(_BIBLIOGRAPHY) + 1},
        {"verbatim_entry": "@article{exactKey,title={Changed}}"},
    ),
)
def test__binding__rejects_mismatched_observation(
    changed: dict[str, object],
) -> None:
    observation = _observation()
    forged = object.__new__(SourceBibliographyObservation)
    for name, value in vars(observation).items():
        object.__setattr__(forged, name, changed.get(name, value))

    with pytest.raises(ValueError, match="conflicts"):
        CitationBibliographyObservationBinding(
            entry=_entry(),
            observation=forged,
        )


def test__binding__rejects_noncanonical_runtime_types() -> None:
    class DerivedEntry(CitationTargetBibliographyEntry):  # type: ignore[misc]
        pass

    entry = _entry()
    derived = DerivedEntry(
        **{
            item.name: getattr(entry, item.name)
            for item in fields(entry)
            if item.init
        }
    )
    with pytest.raises(TypeError, match="CitationTargetBibliographyEntry"):
        CitationBibliographyObservationBinding(
            entry=derived,
            observation=_observation(),
        )
