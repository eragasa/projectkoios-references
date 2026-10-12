"""Ownership tests for explicit selected-bibliography omission guards."""

from projectkoios.references.courses.authority.scope import (
    CourseDisplayCitekeyStatus,
)
from projectkoios.references.courses.authority.selected_bibliography import (
    CourseReferenceSelectedBibliographyOmission,
)


def test_omission__is_explicit_and_non_mutating() -> None:
    value = CourseReferenceSelectedBibliographyOmission(
        predecessor_ordinal=3,
        predecessor_selection_id=(
            "course-reference-selection:sha256:" + "a" * 64
        ),
        predecessor_locator_binding_id=(
            "course-reference-locator-binding:sha256:" + "b" * 64
        ),
        reference_locator=(
            "candidate-bibliography-rendered-entry:sha256:" + "c" * 64
        ),
        display_citekey="omitted2025",
        display_citekey_status=CourseDisplayCitekeyStatus.OBSERVED,
    )
    assert value.predecessor_ordinal == 3
