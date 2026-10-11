"""Tests for the References-owned Courses authority boundary.

The module verifies immutable contracts without assuming cross-repository
ownership.
"""

from projectkoios.base import DataObjectModel
from projectkoios.references.courses.authority import (
    ReferenceAuthorityIdempotencyLookupResult,
)


def test__ReferenceAuthorityIdempotencyLookupResult__is_data_object() -> None:
    """Verify the named owner contract behavior.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    assert issubclass(
        ReferenceAuthorityIdempotencyLookupResult,
        DataObjectModel,
    )
