"""Ownership tests for retained selected-bibliography result items."""

import hashlib

from projectkoios.references.courses.authority.scope import (
    CourseDisplayCitekeyStatus,
)
from projectkoios.references.courses.authority.selected_bibliography import (
    CourseReferenceSelectedBibliographyItem,
)


def test_item__binds_rendered_bytes_to_current_authority() -> None:
    rendered = b"@book{example2026,\n  title = {Example},\n}\n"
    value = CourseReferenceSelectedBibliographyItem(
        new_ordinal=1,
        predecessor_selection_id=(
            "course-reference-selection:sha256:" + "a" * 64
        ),
        predecessor_locator_binding_id=(
            "course-reference-locator-binding:sha256:" + "b" * 64
        ),
        reference_locator=(
            "candidate-bibliography-rendered-entry:sha256:" + "c" * 64
        ),
        display_citekey="example2026",
        display_citekey_status=CourseDisplayCitekeyStatus.OBSERVED,
        rendered_entry_id=(
            "candidate-bibliography-rendered-entry:sha256:" + "c" * 64
        ),
        candidate_id="reference-candidate:sha256:" + "d" * 64,
        source_observation_ids=("bibliography-observation:sha256:" + "e" * 64,),
        current_authority_projection_id=(
            "reference-state-projection:sha256:" + "f" * 64
        ),
        rendered_sha256=hashlib.sha256(rendered).hexdigest(),
        rendered_byte_size=len(rendered),
        rendered_entry=rendered,
    )
    assert value.rendered_entry == rendered
