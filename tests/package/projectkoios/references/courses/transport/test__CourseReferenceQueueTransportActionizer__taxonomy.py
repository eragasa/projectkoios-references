"""Taxonomy contract for CourseReferenceQueueTransportActionizer."""

import inspect

from projectkoios.base import DataObjectActionizer
from projectkoios.references.courses.transport.queue import (
    CourseReferenceQueueTransportActionizer as Contract,
)


def test__contract__uses_declared_taxonomy() -> None:
    """Require the exact immutable single-action taxonomy."""
    assert issubclass(Contract, DataObjectActionizer)
    signature = inspect.signature(Contract.action)
    assert tuple(signature.parameters) == ("self", "request")
    assert (
        signature.parameters["request"].kind is inspect.Parameter.KEYWORD_ONLY
    )
    declared = {
        key
        for key, value in vars(Contract).items()
        if callable(value) and not key.startswith("__")
    }
    assert declared == {"action"}
