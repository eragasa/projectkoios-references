from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from typing import final

from projectkoios.base import DataObjectModel
from projectkoios.references.citations._contract import stable_id
from projectkoios.references.citations.base import (
    CitationTargetBibliographyEntry,
)
from projectkoios.references.identity import SourceBibliographyObservation


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class CitationBibliographyObservationBinding(DataObjectModel):
    """Exact target-entry binding to one References source observation."""

    entry: CitationTargetBibliographyEntry
    observation: SourceBibliographyObservation
    binding_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.entry) is not CitationTargetBibliographyEntry:
            raise TypeError("entry must be a CitationTargetBibliographyEntry")
        if type(self.observation) is not SourceBibliographyObservation:
            raise TypeError(
                "observation must be a SourceBibliographyObservation"
            )
        if (
            self.observation.observed_citekey != self.entry.key
            or self.observation.entry_index != self.entry.entry_index
            or self.observation.source_path != self.entry.locator.source_path
            or self.observation.bibliography_sha256
            != self.entry.locator.source_content_identity.digest
            or self.observation.bibliography_byte_size
            != self.entry.locator.source_content_identity.byte_count
        ):
            raise ValueError(
                "bibliography observation conflicts with target entry"
            )
        verbatim = self.observation.verbatim_entry.encode("utf-8")
        if (
            hashlib.sha256(verbatim).hexdigest()
            != self.entry.entry_content_identity.digest
            or len(verbatim) != self.entry.entry_content_identity.byte_count
        ):
            raise ValueError(
                "bibliography observation verbatim entry conflicts"
            )
        if (
            self.entry.source_bibliography_observation_id is not None
            and self.entry.source_bibliography_observation_id
            != self.observation.observation_id
        ):
            raise ValueError(
                "target bibliography observation identity conflicts"
            )
        object.__setattr__(
            self,
            "binding_id",
            stable_id(
                "citation-bibliography-binding",
                {
                    "entry_id": self.entry.entry_id,
                    "observation_id": self.observation.observation_id,
                },
            ),
        )

    def validate_identity(self) -> None:
        if replace(self.observation) != self.observation:
            raise ValueError(
                "source bibliography observation does not match replay"
            )
        rebuilt = replace(self)
        if rebuilt != self:
            raise ValueError("bibliography binding does not match replay")
