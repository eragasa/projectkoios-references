"""Taxonomy contract for one public Courses class."""

import dataclasses

from projectkoios.base import DataObjectActionResult
from projectkoios.references.courses.runtime.facade import (
    FilesystemCourseReferenceAuthorityRuntimeCreateResult as Contract,
)


def test__contract__uses_declared_taxonomy() -> None:
    """Require the exact immutable single-action taxonomy."""
    assert issubclass(Contract, DataObjectActionResult)
    assert dataclasses.is_dataclass(Contract)
    assert hasattr(Contract, "__slots__")
