"""Composition root for authorized filesystem capabilities."""

from __future__ import annotations

from typing import final

from projectkoios.references.path_safety.observation import (
    AuthorizedRootObservation,
)
from projectkoios.references.path_safety.publication import (
    AuthorizedRootPublication,
)
from projectkoios.references.path_safety.scanning import (
    AuthorizedRootScanning,
)


@final
class AuthorizedRoot(
    AuthorizedRootObservation,
    AuthorizedRootPublication,
    AuthorizedRootScanning,
):
    """Provide one descriptor-confined root capability."""

    __slots__ = ()
