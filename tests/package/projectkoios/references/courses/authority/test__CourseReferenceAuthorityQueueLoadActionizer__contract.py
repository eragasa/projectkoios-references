"""Tests for the References-owned Courses authority boundary.

The module verifies immutable contracts without assuming cross-repository
ownership.
"""

from projectkoios.base import DataObjectActionizer
from projectkoios.references.courses.authority.queue_operation import (
    CourseReferenceAuthorityQueueLoadActionizer,
)


def test__CourseReferenceAuthorityQueueLoadActionizer__is_actionizer() -> None:
    """Verify the named owner contract behavior.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    assert issubclass(
        CourseReferenceAuthorityQueueLoadActionizer,
        DataObjectActionizer,
    )
