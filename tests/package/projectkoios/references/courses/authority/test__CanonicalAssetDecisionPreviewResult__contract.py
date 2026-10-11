"""Tests for the References-owned Courses authority boundary.

The module verifies immutable contracts without assuming cross-repository
ownership.
"""

from projectkoios.base import DataObjectActionResult
from projectkoios.references.courses.authority.asset_preview import (
    CanonicalAssetDecisionPreviewResult,
)


def test_CanonicalAssetDecisionPreviewResult__is_action_result() -> None:
    """Verify the named owner contract behavior.

    Returns
    -------
    object
        Immutable typed output governed by the return annotation.

    """
    assert issubclass(
        CanonicalAssetDecisionPreviewResult,
        DataObjectActionResult,
    )
