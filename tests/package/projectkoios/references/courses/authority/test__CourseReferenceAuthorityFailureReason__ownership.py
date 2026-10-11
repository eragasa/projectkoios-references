"""Class ownership coverage.

The test prevents accidental movement outside the References-owned course
boundary.
"""

from projectkoios.references.courses.authority.service import (
    CourseReferenceAuthorityFailureReason,
)


# A dedicated file keeps ownership coverage discoverable by class name.
def test__owner_module() -> None:
    """Verify that the class remains in its declared owner module.

    Returns
    -------
    None
        The assertion completes without producing an artifact.
    """
    assert (
        CourseReferenceAuthorityFailureReason.__module__
        == "projectkoios.references.courses.authority.service"
    )
