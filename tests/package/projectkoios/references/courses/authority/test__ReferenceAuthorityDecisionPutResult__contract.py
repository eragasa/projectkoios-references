"""Tests for the References-owned Courses authority boundary.

The module verifies immutable contracts without assuming cross-repository
ownership.
"""

from projectkoios.base import DataObjectActionResult
from projectkoios.references.courses.authority.put_result import (
    ReferenceAuthorityDecisionPutResult,
)


def test__ReferenceAuthorityDecisionPutResult__is_action_result() -> None:
    """Verify the named owner contract behavior.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    assert issubclass(
        ReferenceAuthorityDecisionPutResult,
        DataObjectActionResult,
    )
