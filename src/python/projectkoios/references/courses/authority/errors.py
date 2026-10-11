"""Course authority domain failure contract."""

from __future__ import annotations


class CourseReferenceAuthorityError(ValueError):
    """Report invalid queue evidence or authority transition invariants."""
