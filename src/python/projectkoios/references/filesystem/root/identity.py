from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from projectkoios.references.filesystem.root.preflight.evidence import (
    RootPreflightEvidence,
)


@dataclass(frozen=True, slots=True)
class AuthorizedRootIdentity:
    """Immutable filesystem identity without live probes or capabilities."""

    path: Path
    label: str
    device: int
    inode: int
    preflight_evidence: RootPreflightEvidence
    mount_id: int | None = None
