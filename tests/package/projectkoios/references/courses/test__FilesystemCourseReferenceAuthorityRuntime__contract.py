"""Tests for the References-owned Courses authority boundary.

The module verifies immutable contracts without assuming cross-repository
ownership.
"""

from projectkoios.references.courses.runtime import (
    FilesystemCourseReferenceAuthorityRuntime,
)


def test__FilesystemCourseReferenceAuthorityRuntime__declares_slots() -> None:
    """Verify the named owner contract behavior.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    assert FilesystemCourseReferenceAuthorityRuntime.__slots__ == (
        "asset_preview",
        "asset_put",
        "identity_preview",
        "identity_put",
        "queue",
    )
