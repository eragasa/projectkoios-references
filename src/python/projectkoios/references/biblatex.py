from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from projectkoios.references.identity import (
    ProducerIdentity,
    ReferenceCandidate,
    SourceBibliographyObservation,
)
from projectkoios.references.io_limits import (
    BIBLIOGRAPHY_IO_LIMITS,
    ReferenceIOLimitError,
    ReferenceIOLimits,
    bounded_utf8_size,
)
from projectkoios.references.models import normalize_doi
from projectkoios.references.path_safety import (
    CloudPlaceholderProbe,
    PathLimitError,
    RootPreflightEvidence,
    RootStorageClass,
    authorize_root_preflight,
    read_path_bytes,
)


class BibLaTeXUnavailableError(RuntimeError):
    """Raised when the optional BibLaTeX parser is unavailable."""


class BibLaTeXImportError(ValueError):
    """Raised when exact source entries cannot be retained safely."""


def biblatex_parser_identity() -> str:
    try:
        return f"pybtex@{version('pybtex')}"
    except PackageNotFoundError:
        return "pybtex@uninstalled"


@dataclass(frozen=True)
class BibliographyImport:
    bibliography_bytes: bytes
    observations: tuple[SourceBibliographyObservation, ...]
    candidates: tuple[ReferenceCandidate, ...]
    effective_limits: ReferenceIOLimits
    effective_limits_id: str
    root_preflight: RootPreflightEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.bibliography_bytes, bytes) or not (
            self.bibliography_bytes
        ):
            raise ValueError("bibliography import must retain non-empty bytes")
        if not isinstance(self.observations, tuple) or any(
            not isinstance(item, SourceBibliographyObservation)
            for item in self.observations
        ):
            raise ValueError("bibliography observations must be a typed tuple")
        if not isinstance(self.candidates, tuple) or any(
            not isinstance(item, ReferenceCandidate) for item in self.candidates
        ):
            raise ValueError("bibliography candidates must be a typed tuple")
        if self.effective_limits_id != self.effective_limits.evidence_id:
            raise ValueError("bibliography I/O-limit identity conflicts")
        bibliography_digest = hashlib.sha256(
            self.bibliography_bytes
        ).hexdigest()
        if any(
            item.bibliography_sha256 != bibliography_digest
            or item.bibliography_byte_size != len(self.bibliography_bytes)
            for item in self.observations
        ):
            raise ValueError(
                "bibliography observations conflict with retained bytes"
            )
        observation_keys = tuple(
            item.observed_citekey for item in self.observations
        )
        candidate_keys = tuple(
            item.proposed_citekey for item in self.candidates
        )
        if observation_keys != candidate_keys or any(
            observation.observation_id not in candidate.source_observation_ids
            for observation, candidate in zip(
                self.observations,
                self.candidates,
                strict=True,
            )
        ):
            raise ValueError(
                "bibliography observations and candidates are not aligned"
            )


def load_bibliography(
    path: Path,
    *,
    source_id: str,
    storage_class: RootStorageClass,
    placeholder_probe: CloudPlaceholderProbe | None = None,
    source_revision: str | None = None,
    source_path: str | None = None,
    limits: ReferenceIOLimits = BIBLIOGRAPHY_IO_LIMITS,
) -> BibliographyImport:
    """Observe exact BibTeX entries and derive noncanonical candidates."""
    try:
        from pybtex.database import parse_string  # type: ignore[import-untyped]
    except ImportError as error:  # pragma: no cover - environment dependent
        raise BibLaTeXUnavailableError(
            "BibLaTeX import requires the 'bibtex' project extra"
        ) from error

    root_preflight = authorize_root_preflight(
        root_alias="bibliography",
        storage_class=storage_class,
        placeholder_probe=placeholder_probe,
    )
    max_bytes = _required_limit(
        limits.max_bibliography_bytes,
        "max_bibliography_bytes",
    )
    try:
        content = read_path_bytes(
            path,
            label="bibliography",
            root_alias="bibliography",
            storage_class=storage_class,
            placeholder_probe=placeholder_probe,
            max_bytes=max_bytes,
        )
    except PathLimitError as error:
        raise ReferenceIOLimitError(
            resource=error.resource,
            limit_name="max_bibliography_bytes",
            limit=max_bytes,
            observed=error.observed,
            limits=limits,
        ) from error
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BibLaTeXImportError("bibliography is not UTF-8") from error
    verbatim = _verbatim_entries(text, limits=limits)
    database: Any = parse_string(text, bib_format="bibtex")
    database_keys = tuple(str(key) for key in database.entries)
    if set(verbatim) != set(database_keys):
        missing = sorted(set(database_keys) - set(verbatim))
        extra = sorted(set(verbatim) - set(database_keys))
        raise BibLaTeXImportError(
            "verbatim entry recovery differs from parsed bibliography: "
            f"missing={missing}, extra={extra}"
        )

    occurrence_path = source_path or path.name
    parser_name, _, parser_version = biblatex_parser_identity().partition("@")
    parser = ProducerIdentity(parser_name, parser_version)
    generator = ProducerIdentity(
        "projectkoios.references.biblatex-normalizer",
        "1",
    )
    observations: list[SourceBibliographyObservation] = []
    candidates: list[ReferenceCandidate] = []
    for citekey, entry in database.entries.items():
        fields = {
            str(key).lower(): str(value) for key, value in entry.fields.items()
        }
        authors = tuple(
            str(person) for person in entry.persons.get("author", ())
        )
        year = fields.get("year") or fields.get("date")
        entry_index, verbatim_entry = verbatim[str(citekey)]
        observation = SourceBibliographyObservation.create(
            source_id=source_id,
            asserted_source_revision=source_revision,
            source_path=occurrence_path,
            bibliography_bytes=content,
            entry_index=entry_index,
            observed_citekey=str(citekey),
            verbatim_entry=verbatim_entry,
            parser=parser,
        )
        candidate = ReferenceCandidate.create(
            proposed_citekey=str(citekey),
            entry_type=str(entry.type).lower(),
            title=fields.get("title"),
            authors=authors,
            year=year,
            doi=normalize_doi(fields.get("doi")),
            isbn=fields.get("isbn"),
            url=fields.get("url"),
            eprint=fields.get("eprint"),
            source_observation_ids=(observation.observation_id,),
            generator=generator,
        )
        observations.append(observation)
        candidates.append(candidate)

    ordered = sorted(
        zip(observations, candidates, strict=True),
        key=lambda pair: pair[0].entry_index,
    )
    return BibliographyImport(
        bibliography_bytes=content,
        observations=tuple(item[0] for item in ordered),
        candidates=tuple(item[1] for item in ordered),
        effective_limits=limits,
        effective_limits_id=limits.evidence_id,
        root_preflight=root_preflight,
    )


def _verbatim_entries(
    text: str,
    *,
    limits: ReferenceIOLimits = BIBLIOGRAPHY_IO_LIMITS,
) -> dict[str, tuple[int, str]]:
    entries: dict[str, tuple[int, str]] = {}
    cursor = 0
    entry_index = 0
    while True:
        marker = text.find("@", cursor)
        if marker < 0:
            break
        type_end = marker + 1
        while type_end < len(text) and (
            text[type_end].isalnum() or text[type_end] in "_-"
        ):
            type_end += 1
        entry_type = text[marker + 1 : type_end].lower()
        opening_index = type_end
        while opening_index < len(text) and text[opening_index].isspace():
            opening_index += 1
        if opening_index >= len(text) or text[opening_index] not in "{(":
            cursor = marker + 1
            continue
        closing_index = _matching_entry_end(
            text,
            opening_index,
            limits=limits,
        )
        raw = text[marker : closing_index + 1]
        max_text_bytes = _required_limit(
            limits.max_text_bytes,
            "max_text_bytes",
        )
        raw_bytes = bounded_utf8_size(raw, max_bytes=max_text_bytes)
        if raw_bytes > max_text_bytes:
            raise ReferenceIOLimitError(
                resource="bibliography entry",
                limit_name="max_text_bytes",
                limit=max_text_bytes,
                observed=raw_bytes,
                limits=limits,
            )
        body = text[opening_index + 1 : closing_index]
        cursor = closing_index + 1
        if entry_type in {"comment", "preamble", "string"}:
            continue
        comma = body.find(",")
        if comma < 0:
            raise BibLaTeXImportError(
                f"bibliography entry has no citekey terminator: {entry_type}"
            )
        citekey = body[:comma].strip()
        if not citekey:
            raise BibLaTeXImportError("bibliography entry has an empty citekey")
        if citekey in entries:
            raise BibLaTeXImportError(
                f"bibliography contains duplicate citekey: {citekey}"
            )
        entries[citekey] = (entry_index, raw)
        entry_index += 1
        max_entries = _required_limit(limits.max_entries, "max_entries")
        if entry_index > max_entries:
            raise ReferenceIOLimitError(
                resource="bibliography",
                limit_name="max_entries",
                limit=max_entries,
                observed=entry_index,
                limits=limits,
            )
    return entries


def _matching_entry_end(
    text: str,
    opening_index: int,
    *,
    limits: ReferenceIOLimits,
) -> int:
    max_depth = _required_limit(
        limits.max_nesting_depth,
        "max_nesting_depth",
    )
    opening = text[opening_index]
    closing = "}" if opening == "{" else ")"
    depth = 1
    brace_depth = 0
    quoted = False
    escaped = False
    for index in range(opening_index + 1, len(text)):
        character = text[index]
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == '"':
            quoted = not quoted
            continue
        if opening == "{" and character == "{":
            depth += 1
            if depth > max_depth:
                raise _nesting_limit_error(max_depth, limits)
            continue
        if opening == "{" and character == "}":
            depth -= 1
            if depth == 0:
                return index
            continue
        if opening == "(" and character == "{":
            brace_depth += 1
            if depth + brace_depth > max_depth:
                raise _nesting_limit_error(max_depth, limits)
            continue
        if opening == "(" and character == "}" and brace_depth:
            brace_depth -= 1
            continue
        if quoted or brace_depth:
            continue
        if character == opening:
            depth += 1
            if depth > max_depth:
                raise _nesting_limit_error(max_depth, limits)
        elif character == closing:
            depth -= 1
            if depth == 0:
                return index
    raise BibLaTeXImportError("bibliography contains an unterminated entry")


def _nesting_limit_error(
    limit: int,
    limits: ReferenceIOLimits,
) -> ReferenceIOLimitError:
    return ReferenceIOLimitError(
        resource="bibliography entry nesting",
        limit_name="max_nesting_depth",
        limit=limit,
        observed=limit + 1,
        limits=limits,
    )


def _required_limit(value: int | None, name: str) -> int:
    if value is None:
        raise ValueError(f"bibliography I/O profile must define {name}")
    return value
