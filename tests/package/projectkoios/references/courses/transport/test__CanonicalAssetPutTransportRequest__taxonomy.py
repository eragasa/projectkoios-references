"""Taxonomy contract for CanonicalAssetPutTransportRequest."""

import dataclasses

from projectkoios.base import DataObjectActionRequest
from projectkoios.references.courses.transport.asset import (
    CanonicalAssetPutTransportRequest as Contract,
)


def test__contract__uses_declared_taxonomy() -> None:
    """Require the exact immutable single-action taxonomy."""
    assert issubclass(Contract, DataObjectActionRequest)
    assert dataclasses.is_dataclass(Contract)
    assert hasattr(Contract, "__slots__")
