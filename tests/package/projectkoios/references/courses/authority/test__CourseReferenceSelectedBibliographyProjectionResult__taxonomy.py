"""Taxonomy tests for selected-bibliography projection results."""

from projectkoios.base import DataObjectActionResult
from projectkoios.references.courses.authority.selected_bibliography import (
    CourseReferenceSelectedBibliographyProjectionResult,
)


def test_result__is_immutable_action_result() -> None:
    assert issubclass(
        CourseReferenceSelectedBibliographyProjectionResult,
        DataObjectActionResult,
    )
