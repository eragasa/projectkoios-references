"""Ownership tests for path-free selected-bibliography provenance."""

from projectkoios.references.courses.authority.selected_bibliography import (
    CourseReferenceSelectedBibliographyProvenance,
)


def test_provenance__contains_no_source_path() -> None:
    value = CourseReferenceSelectedBibliographyProvenance(
        collection_id="collection",
        declaration_id=(
            "candidate-bibliography-source-declaration:sha256:" + "a" * 64
        ),
        source_id="source:collection",
        asserted_source_revision="sha256:" + "b" * 64,
        bibliography_sha256="c" * 64,
        bibliography_byte_size=10,
        observation_ids=("bibliography-observation:sha256:" + "d" * 64,),
    )
    assert "path" not in value.__dataclass_fields__
