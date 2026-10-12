"""Taxonomy tests for selected-bibliography projection requests."""

from projectkoios.base import DataObjectActionRequest
from projectkoios.references.courses.authority.selected_bibliography import (
    CourseReferenceSelectedBibliographyProjectionRequest,
)


def test_request__is_immutable_action_request() -> None:
    assert issubclass(
        CourseReferenceSelectedBibliographyProjectionRequest,
        DataObjectActionRequest,
    )
