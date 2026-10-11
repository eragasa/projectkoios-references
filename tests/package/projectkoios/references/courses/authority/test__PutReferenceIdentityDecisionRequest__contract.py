"""Tests for the References-owned Courses authority boundary.

The module verifies immutable contracts without assuming cross-repository
ownership.
"""

from projectkoios.base import DataObjectActionRequest
from projectkoios.references.courses.authority.identity_put import (
    PutReferenceIdentityDecisionRequest,
)


def test__PutReferenceIdentityDecisionRequest__is_action_request() -> None:
    """Verify the named owner contract behavior.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    assert issubclass(
        PutReferenceIdentityDecisionRequest,
        DataObjectActionRequest,
    )
