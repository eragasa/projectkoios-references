from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from projectkoios.references.identity import (
    ProducerIdentity,
    ReferenceCandidate,
    SourceBibliographyObservation,
)
from projectkoios.references.models import normalize_doi
from projectkoios.references.path_safety import read_path_bytes

_MAX_BIBLIOGRAPHY_BYTES = 50_000_000


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
    observations: tuple[SourceBibliographyObservation, ...]
    candidates: tuple[ReferenceCandidate, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.observations, tuple) or any(
            not isinstance(item, SourceBibliographyObservation)
            for item in self.observations
        ):
            raise ValueError("bibliography observations must be a typed tuple")
        if not isinstance(self.candidates, tuple) or any(
            not isinstance(item, ReferenceCandidate) for item in self.candidates
        ):
            raise ValueError("bibliography candidates must be a typed tuple")
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
    source_revision: str | None = None,
    source_path: str | None = None,
) -> BibliographyImport:
    """Observe exact BibTeX entries and derive noncanonical candidates."""
    try:
        from pybtex.database import parse_string  # type: ignore[import-untyped]
    except ImportError as error:  # pragma: no cover - environment dependent
        raise BibLaTeXUnavailableError(
            "BibLaTeX import requires the 'bibtex' project extra"
        ) from error

    content = read_path_bytes(
        path,
        label="bibliography",
        max_bytes=_MAX_BIBLIOGRAPHY_BYTES,
    )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BibLaTeXImportError("bibliography is not UTF-8") from error
    database: Any = parse_string(text, bib_format="bibtex")
    verbatim = _verbatim_entries(text)
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
        observations=tuple(item[0] for item in ordered),
        candidates=tuple(item[1] for item in ordered),
    )


def _verbatim_entries(text: str) -> dict[str, tuple[int, str]]:
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
        closing_index = _matching_entry_end(text, opening_index)
        raw = text[marker : closing_index + 1]
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
    return entries


def _matching_entry_end(text: str, opening_index: int) -> int:
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
        if quoted:
            continue
        if opening == "(" and character == "{":
            brace_depth += 1
            continue
        if opening == "(" and character == "}" and brace_depth:
            brace_depth -= 1
            continue
        if brace_depth:
            continue
        if character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return index
    raise BibLaTeXImportError("bibliography contains an unterminated entry")
