"""Ownership tests for selected bibliography input values."""

import hashlib

from projectkoios.references.courses.authority.scope import (
    CourseDisplayCitekeyStatus,
)
from projectkoios.references.courses.authority.selected_bibliography import (
    CourseReferenceSelectedBibliographySelection,
)


def test_selection__retains_exact_opaque_locator() -> None:
    locator = "candidate-bibliography-rendered-entry:sha256:" + "a" * 64
    value = CourseReferenceSelectedBibliographySelection(
        new_ordinal=1,
        predecessor_selection_id=(
            "course-reference-selection:sha256:"
            + hashlib.sha256(b"selection").hexdigest()
        ),
        predecessor_locator_binding_id=(
            "course-reference-locator-binding:sha256:"
            + hashlib.sha256(b"binding").hexdigest()
        ),
        reference_locator=locator,
        display_citekey="example2026",
        display_citekey_status=(
            CourseDisplayCitekeyStatus.PROPOSED_NONCANONICAL
        ),
        expected_candidate_id="reference-candidate:sha256:" + "b" * 64,
        expected_current_authority_projection_id=(
            "reference-state-projection:sha256:" + "c" * 64
        ),
    )
    assert value.reference_locator == locator
