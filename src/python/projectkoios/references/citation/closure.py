from __future__ import annotations

import hashlib
import heapq
import os
import posixpath
import re
import selectors
import subprocess
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath

from projectkoios.references.io_limits import (
    RECONCILIATION_IO_LIMITS,
    ReferenceIOLimitError,
    ReferenceIOLimits,
)
from projectkoios.references.path_safety import (
    AuthorizedRoot,
    CloudPlaceholderProbe,
    PathLimitError,
    PathSafetyError,
    RootPreflightEvidence,
    RootStorageClass,
    validate_citekey,
    validate_relative_path,
)
from projectkoios.references.reconciliation_package import (
    ContentEvidence,
    VerifiedSourceTree,
    canonical_json_bytes,
    pretty_json,
)

CITATION_CLOSURE_SCHEMA_VERSION = 5
CITATION_PARSER_NAME = "projectkoios-bounded-latex-citation-observer"
CITATION_PARSER_VERSION = "2"
_GIT_STATUS_CHUNK_BYTES = 8192
_GIT_STATUS_TIMEOUT_SECONDS = 30.0

_UNSUPPORTED_DEFINITION_COMMANDS = frozenset(
    {
        "DeclareDocumentCommand",
        "DeclareDocumentEnvironment",
        "DeclareMathOperator",
        "DeclarePairedDelimiter",
        "DeclareRobustCommand",
        "NewDocumentCommand",
        "NewDocumentEnvironment",
        "NewExpandableDocumentCommand",
        "ProvideDocumentCommand",
        "ProvideDocumentEnvironment",
        "ProvideExpandableDocumentCommand",
        "RenewDocumentCommand",
        "RenewDocumentEnvironment",
        "RenewExpandableDocumentCommand",
        "newenvironment",
        "newif",
        "renewenvironment",
    }
)


def _safe_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z][A-Za-z@]*\*?", value) is not None
    )


def _safe_command_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z][A-Za-z@]*", value) is not None
    )


class CitationScanMode(StrEnum):
    """Explicit source-selection semantics for citation observation."""

    BUILD_GRAPH = "build-graph"
    ALL_FILES_OBSERVATION = "all-files-observation"


@dataclass(frozen=True)
class CitationParserConfiguration:
    """Versioned, literal-only citation/parser contract.

    This configuration is deliberately not a TeX interpreter. Commands and
    aliases are recognized only by exact name, and include targets and citekeys
    must be literal.
    """

    schema_version: int = 1
    parser_name: str = CITATION_PARSER_NAME
    parser_version: str = CITATION_PARSER_VERSION
    citation_commands: tuple[str, ...] = (
        "Autocite",
        "Cite",
        "Parencite",
        "Smartcite",
        "Textcite",
        "autocite",
        "cite",
        "citealp",
        "citealt",
        "citeauthor",
        "citep",
        "citet",
        "citeyear",
        "citeyearpar",
        "footcite",
        "footcitetext",
        "parencite",
        "smartcite",
        "supercite",
        "textcite",
    )
    multicite_commands: tuple[str, ...] = (
        "Autocites",
        "Cites",
        "Parencites",
        "Smartcites",
        "Textcites",
        "autocites",
        "cites",
        "footcites",
        "parencites",
        "smartcites",
        "textcites",
    )
    aliases: tuple[tuple[str, str], ...] = ()
    include_commands: tuple[str, ...] = ("include", "input")
    verbatim_environments: tuple[str, ...] = (
        "Verbatim",
        "comment",
        "lstlisting",
        "minted",
        "verbatim",
        "verbatim*",
    )
    max_optional_arguments: int = 2
    max_group_depth: int = 64

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported citation-parser configuration")
        if (
            self.parser_name != CITATION_PARSER_NAME
            or self.parser_version != CITATION_PARSER_VERSION
        ):
            raise ValueError("unsupported citation-parser identity")
        command_groups = (
            self.citation_commands,
            self.multicite_commands,
            self.include_commands,
        )
        for values in (*command_groups, self.verbatim_environments):
            validator = (
                _safe_name
                if values is self.verbatim_environments
                else _safe_command_name
            )
            if (
                not isinstance(values, tuple)
                or values != tuple(sorted(values))
                or len(values) != len(set(values))
                or any(not validator(item) for item in values)
            ):
                raise ValueError(
                    "citation-parser command sets must be sorted and unique"
                )
        if (
            type(self.max_optional_arguments) is not int
            or not 0 <= self.max_optional_arguments <= 4
            or type(self.max_group_depth) is not int
            or not 1 <= self.max_group_depth <= 128
        ):
            raise ValueError("citation-parser bounds are outside hard limits")
        aliases = dict(self.aliases)
        if (
            tuple(sorted(self.aliases)) != self.aliases
            or len(aliases) != len(self.aliases)
            or any(not _safe_command_name(alias) for alias in aliases)
        ):
            raise ValueError("citation aliases must be sorted and unique")
        targets = (
            set(self.citation_commands)
            | set(self.multicite_commands)
            | {"nocite"}
        )
        if any(target not in targets for target in aliases.values()):
            raise ValueError("citation alias target is not a supported command")
        reserved = targets | set(self.include_commands)
        if set(aliases) & reserved:
            raise ValueError("citation aliases cannot shadow built-in commands")

    @property
    def configuration_id(self) -> str:
        return _stable_id("citation-parser-configuration", asdict(self))


DEFAULT_CITATION_PARSER_CONFIGURATION = CitationParserConfiguration()


@dataclass(frozen=True)
class CitationLocator:
    source_path: str
    line: int
    column: int
    command: str

    def __post_init__(self) -> None:
        validate_relative_path(self.source_path, field="citation source path")
        if type(self.line) is not int or self.line < 1:
            raise ValueError("citation locator line must be positive")
        if type(self.column) is not int or self.column < 1:
            raise ValueError("citation locator column must be positive")
        if not _safe_name(self.command):
            raise ValueError("citation locator command is invalid")

    @property
    def relative_locator(self) -> str:
        return f"{self.source_path}:{self.line}:{self.column}"


@dataclass(frozen=True)
class CitationUse:
    citekey: str
    source_files: tuple[str, ...]
    locators: tuple[CitationLocator, ...]

    def __post_init__(self) -> None:
        validate_citekey(self.citekey)
        expected_files = tuple(
            sorted({locator.source_path for locator in self.locators})
        )
        expected_locators = tuple(
            sorted(
                set(self.locators),
                key=lambda item: (
                    item.source_path,
                    item.line,
                    item.column,
                    item.command,
                ),
            )
        )
        if (
            self.source_files != expected_files
            or not self.locators
            or self.locators != expected_locators
        ):
            raise ValueError("citation use files must derive from its locators")


@dataclass(frozen=True)
class CitationSourceFile:
    relative_path: str
    byte_size: int
    sha256: str

    def __post_init__(self) -> None:
        validate_relative_path(self.relative_path, field="citation source path")
        if type(self.byte_size) is not int or self.byte_size < 0:
            raise ValueError("citation source size must be nonnegative")
        if re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ValueError("citation source digest must be lowercase SHA-256")


@dataclass(frozen=True)
class CitationSourceEdge:
    command: str
    source_path: str
    target_path: str
    source_locator: str

    def __post_init__(self) -> None:
        if self.command not in {"include", "input"}:
            raise ValueError("unsupported citation source-edge command")
        validate_relative_path(self.source_path, field="source-edge source")
        validate_relative_path(self.target_path, field="source-edge target")
        if not self.source_locator.startswith(f"{self.source_path}:"):
            raise ValueError("source-edge locator is not source-relative")


class CitationCoverageIncomplete(RuntimeError):
    """Typed failure: bounded parsing cannot support a closure claim."""

    code = "citation-coverage-incomplete"
    coverage_status = "incomplete"

    def __init__(
        self,
        *,
        reason_code: str,
        message: str,
        mode: CitationScanMode,
        entrypoint: str | None,
        parser_configuration: CitationParserConfiguration,
        limits: ReferenceIOLimits,
        source_locator: str | None = None,
    ) -> None:
        self.reason_code = reason_code
        self.detail = message
        self.mode = mode
        self.entrypoint = entrypoint
        self.parser_configuration = parser_configuration
        self.limits = limits
        self.source_locator = source_locator
        super().__init__(f"{message}; citation coverage remains incomplete")

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "coverage_status": self.coverage_status,
            "reason_code": self.reason_code,
            "detail": self.detail,
            "mode": self.mode.value,
            "entrypoint": self.entrypoint,
            "source_locator": self.source_locator,
            "parser_configuration_id": (
                self.parser_configuration.configuration_id
            ),
            "effective_limits": self.limits.to_dict(),
            "effective_limits_id": self.limits.evidence_id,
        }

    def to_json(self) -> str:
        return pretty_json(self.to_dict())


@dataclass(frozen=True)
class CitationClosure:
    """Complete citation-key resolution evidence for one explicit scope."""

    schema_version: int
    coverage_status: str
    authority_boundary: str
    limitations: tuple[str, ...]
    asserted_source_revision: str
    root_preflight: RootPreflightEvidence
    verified_source_tree: VerifiedSourceTree | None
    mode: CitationScanMode
    entrypoint: str | None
    parser_configuration: CitationParserConfiguration
    parser_configuration_id: str
    effective_limits: ReferenceIOLimits
    effective_limits_id: str
    bibliography_keys: tuple[str, ...]
    explicit_uses: tuple[CitationUse, ...]
    cited_and_defined: tuple[str, ...]
    cited_but_undefined: tuple[str, ...]
    defined_but_uncited: tuple[str, ...]
    nocite_all: bool
    include_only: tuple[str, ...] | None
    source_graph: tuple[CitationSourceEdge, ...]
    source_files: tuple[str, ...]
    source_file_identities: tuple[CitationSourceFile, ...]
    source_file_evidence: tuple[ContentEvidence, ...] = field(compare=False)
    closure_id: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != CITATION_CLOSURE_SCHEMA_VERSION:
            raise ValueError("unsupported citation-closure schema")
        if self.coverage_status != "complete":
            raise ValueError(
                "CitationClosure can represent only complete coverage"
            )
        if self.authority_boundary != "citation-key-resolution-only":
            raise ValueError("citation closure authority boundary is invalid")
        if self.parser_configuration_id != (
            self.parser_configuration.configuration_id
        ):
            raise ValueError("citation parser configuration identity differs")
        if self.effective_limits_id != self.effective_limits.evidence_id:
            raise ValueError("citation effective-limits identity differs")
        if self.mode is CitationScanMode.BUILD_GRAPH:
            if self.entrypoint is None:
                raise ValueError(
                    "build-graph citation closure needs an entrypoint"
                )
        elif self.mode is CitationScanMode.ALL_FILES_OBSERVATION:
            if self.entrypoint is not None:
                raise ValueError(
                    "all-files observation cannot claim an entrypoint"
                )
        else:
            raise ValueError("citation closure mode is invalid")
        if self.limitations != (
            "not-canonical-identity-acceptance",
            "not-contract-acceptance",
            "not-full-latex-semantics",
            "not-manuscript-acceptance",
            "not-publication-acceptance",
            "not-rights-clearance",
            "not-scientific-validation",
        ):
            raise ValueError("citation closure limitations are incomplete")
        if self.entrypoint is not None:
            validate_relative_path(self.entrypoint, field="citation entrypoint")
        if self.include_only is not None:
            if self.include_only != tuple(
                sorted(set(self.include_only))
            ) or any(not item for item in self.include_only):
                raise ValueError(
                    "includeonly targets must be sorted and unique"
                )
            for item in self.include_only:
                validate_relative_path(item, field="includeonly target")
        if self.source_files != tuple(
            sorted(set(self.source_files))
        ) or self.source_files != tuple(
            item.relative_path for item in self.source_file_identities
        ):
            raise ValueError("citation source paths differ from identities")
        if (
            self.entrypoint is not None
            and self.entrypoint not in self.source_files
        ):
            raise ValueError(
                "citation entrypoint is absent from source identities"
            )
        evidence_paths = tuple(
            item.filename.removeprefix("inputs/citation-source/")
            for item in self.source_file_evidence
        )
        if evidence_paths != self.source_files:
            raise ValueError("citation source evidence differs from identities")
        for identity, evidence in zip(
            self.source_file_identities,
            self.source_file_evidence,
            strict=True,
        ):
            if (
                identity.byte_size != evidence.byte_size
                or identity.sha256 != evidence.sha256
            ):
                raise ValueError("citation source evidence identity differs")
        if self.bibliography_keys != tuple(sorted(set(self.bibliography_keys))):
            raise ValueError("bibliography keys must be sorted and unique")
        for key in self.bibliography_keys:
            validate_citekey(key, field="bibliography citekey")
        if self.explicit_uses != tuple(
            sorted(self.explicit_uses, key=lambda item: item.citekey)
        ) or len({item.citekey for item in self.explicit_uses}) != len(
            self.explicit_uses
        ):
            raise ValueError("citation uses must be citekey-sorted and unique")
        cited = {item.citekey for item in self.explicit_uses}
        bibliography = set(self.bibliography_keys)
        expected_resolved = (
            bibliography if self.nocite_all else cited & bibliography
        )
        expected_uncited = set() if self.nocite_all else bibliography - cited
        if (
            self.cited_and_defined != tuple(sorted(expected_resolved))
            or self.cited_but_undefined != tuple(sorted(cited - bibliography))
            or self.defined_but_uncited != tuple(sorted(expected_uncited))
        ):
            raise ValueError(
                "citation resolution sets differ from observed uses"
            )
        source_set = set(self.source_files)
        for use in self.explicit_uses:
            if not set(use.source_files) <= source_set:
                raise ValueError("citation use references an unbound source")
        if self.source_graph != tuple(
            sorted(
                self.source_graph,
                key=lambda item: (
                    item.source_path,
                    item.source_locator,
                    item.command,
                    item.target_path,
                ),
            )
        ):
            raise ValueError("citation source graph is not deterministic")
        selected_includes = set(self.include_only or ())
        for edge in self.source_graph:
            if edge.source_path not in source_set:
                raise ValueError("source graph edge has an unbound source")
            if edge.target_path in source_set:
                continue
            inactive_include = (
                self.mode is CitationScanMode.BUILD_GRAPH
                and edge.command == "include"
                and self.include_only is not None
                and edge.target_path.removesuffix(".tex")
                not in selected_includes
            )
            if not inactive_include:
                raise ValueError("source graph edge has an unbound target")
        if self.closure_id != _stable_id("citation-closure", self._payload()):
            raise ValueError("citation closure identity differs from evidence")

    def _payload(self) -> dict[str, object]:
        value = asdict(self)
        value.pop("closure_id", None)
        return value

    def to_json(self) -> str:
        return pretty_json(self)


@dataclass(frozen=True)
class _ParsedFile:
    uses: tuple[tuple[str, CitationLocator], ...]
    edges: tuple[CitationSourceEdge, ...]
    nocite_all: bool
    include_only: tuple[str, ...] | None
    token_count: int
    defined_commands: tuple[str, ...]
    unknown_invocations: tuple[tuple[str, str], ...]


class _ParseFailure(Exception):
    def __init__(self, reason_code: str, message: str, offset: int) -> None:
        self.reason_code = reason_code
        self.detail = message
        self.offset = offset
        super().__init__(message)


class _GitProbeError(RuntimeError):
    """Raised when bounded Git provenance cannot be established safely."""


def build_citation_closure(
    manuscript_root: Path,
    *,
    storage_class: RootStorageClass,
    mode: CitationScanMode,
    entrypoint: str | None,
    placeholder_probe: CloudPlaceholderProbe | None = None,
    bibliography_keys: tuple[str, ...],
    source_revision: str,
    parser_configuration: CitationParserConfiguration = (
        DEFAULT_CITATION_PARSER_CONFIGURATION
    ),
    limits: ReferenceIOLimits = RECONCILIATION_IO_LIMITS,
) -> CitationClosure:
    """Observe citations under the declared bounded scope.

    Success means only that literal citation keys resolve against the supplied
    bibliography under this parser contract. It is not a full LaTeX semantic
    evaluation and grants no canonical, scientific, manuscript, rights,
    publication, review, or contract authority.
    """
    if not isinstance(mode, CitationScanMode):
        raise ValueError("citation mode must be a CitationScanMode")
    if not isinstance(parser_configuration, CitationParserConfiguration):
        raise ValueError("citation parser configuration is invalid")
    if not isinstance(source_revision, str) or not source_revision:
        raise ValueError("asserted source revision must be non-empty")
    normalized_entrypoint: str | None
    if mode is CitationScanMode.BUILD_GRAPH:
        if entrypoint is None:
            raise ValueError("build-graph mode requires a relative entrypoint")
        normalized_entrypoint = _source_path(entrypoint).as_posix()
    else:
        if entrypoint is not None:
            raise ValueError("all-files observation mode forbids an entrypoint")
        normalized_entrypoint = None

    max_citations = _required_limit(limits.max_candidates, "max_candidates")
    if len(bibliography_keys) > max_citations:
        raise ReferenceIOLimitError(
            resource="bibliography citekeys",
            limit_name="max_candidates",
            limit=max_citations,
            observed=len(bibliography_keys),
            limits=limits,
        )
    try:
        bibliography = {
            validate_citekey(key, field="bibliography citekey")
            for key in bibliography_keys
        }
    except PathSafetyError as error:
        raise ValueError(str(error)) from error
    if len(bibliography) != len(bibliography_keys):
        raise ValueError("bibliography citekeys must be unique")

    try:
        root = AuthorizedRoot.existing(
            manuscript_root,
            label="manuscript root",
            root_alias="manuscript-sources",
            storage_class=storage_class,
            placeholder_probe=placeholder_probe,
        )
    except PathSafetyError:
        raise

    if mode is CitationScanMode.ALL_FILES_OBSERVATION:
        try:
            initial_paths = root.iter_files(
                suffix=".tex",
                recursive=True,
                max_files=_required_limit(limits.max_files, "max_files"),
                max_entries=_required_limit(limits.max_entries, "max_entries"),
                max_depth=min(
                    _required_limit(
                        limits.max_nesting_depth, "max_nesting_depth"
                    ),
                    128,
                ),
            )
        except PathLimitError as error:
            raise _limit_error(error, limits) from error
        if not initial_paths:
            raise _incomplete(
                "no-source-files",
                "all-files observation found no TeX source files",
                mode,
                normalized_entrypoint,
                parser_configuration,
                limits,
            )
    else:
        assert normalized_entrypoint is not None
        initial_paths = (PurePosixPath(normalized_entrypoint),)

    pending = [(path, 0) for path in reversed(initial_paths)]
    queued = {path.as_posix() for path in initial_paths}
    visited: set[str] = set()
    raw_by_path: dict[str, bytes] = {}
    parsed_by_path: dict[str, _ParsedFile] = {}
    total_bytes = 0
    max_files = _required_limit(limits.max_files, "max_files")
    max_file_bytes = _required_limit(
        limits.max_text_file_bytes, "max_text_file_bytes"
    )
    max_total_bytes = _required_limit(
        limits.max_text_total_bytes, "max_text_total_bytes"
    )
    max_include_depth = _required_limit(
        limits.max_nesting_depth, "max_nesting_depth"
    )
    citation_count = 0
    parser_token_count = 0
    source_edge_count = 0
    max_parser_entries = _required_limit(limits.max_entries, "max_entries")
    include_only: tuple[str, ...] | None = None

    while pending:
        path, include_depth = pending.pop()
        relative = path.as_posix()
        queued.discard(relative)
        if relative in visited:
            continue
        if len(visited) + 1 > max_files:
            raise ReferenceIOLimitError(
                resource="citation source files",
                limit_name="max_files",
                limit=max_files,
                observed=len(visited) + 1,
                limits=limits,
            )
        try:
            content = root.read_bytes(path, max_bytes=max_file_bytes)
        except PathLimitError as error:
            raise _limit_error(error, limits) from error
        except (FileNotFoundError, PermissionError, PathSafetyError) as error:
            raise _incomplete(
                "source-unavailable",
                f"citation source is unavailable: {relative}",
                mode,
                normalized_entrypoint,
                parser_configuration,
                limits,
                source_locator=relative,
            ) from error
        total_bytes += len(content)
        if total_bytes > max_total_bytes:
            raise ReferenceIOLimitError(
                resource="citation source files",
                limit_name="max_text_total_bytes",
                limit=max_total_bytes,
                observed=total_bytes,
                limits=limits,
            )
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise _incomplete(
                "source-not-utf8",
                f"citation source is not UTF-8: {relative}",
                mode,
                normalized_entrypoint,
                parser_configuration,
                limits,
                source_locator=relative,
            ) from error
        try:
            parsed = _parse_source(
                text,
                source_path=relative,
                configuration=parser_configuration,
                limits=limits,
                citations_observed=citation_count,
            )
        except _ParseFailure as error:
            line, column = _line_column(text, error.offset)
            raise _incomplete(
                error.reason_code,
                error.detail,
                mode,
                normalized_entrypoint,
                parser_configuration,
                limits,
                source_locator=f"{relative}:{line}:{column}",
            ) from error
        if parsed.include_only is not None:
            if (
                mode is CitationScanMode.BUILD_GRAPH
                and relative != normalized_entrypoint
            ):
                raise _incomplete(
                    "ambiguous-includeonly-scope",
                    "includeonly is supported only in the build entrypoint",
                    mode,
                    normalized_entrypoint,
                    parser_configuration,
                    limits,
                    source_locator=relative,
                )
            if include_only is not None and include_only != parsed.include_only:
                raise _incomplete(
                    "ambiguous-includeonly-scope",
                    "multiple distinct includeonly declarations are "
                    "unsupported",
                    mode,
                    normalized_entrypoint,
                    parser_configuration,
                    limits,
                    source_locator=relative,
                )
            include_only = parsed.include_only
        visited.add(relative)
        raw_by_path[relative] = content
        parsed_by_path[relative] = parsed
        citation_count += len(parsed.uses)
        parser_token_count += parsed.token_count
        source_edge_count += len(parsed.edges)
        if parser_token_count > max_parser_entries:
            raise ReferenceIOLimitError(
                resource="citation parser tokens",
                limit_name="max_entries",
                limit=max_parser_entries,
                observed=parser_token_count,
                limits=limits,
            )
        if source_edge_count > max_parser_entries:
            raise ReferenceIOLimitError(
                resource="citation source graph edges",
                limit_name="max_entries",
                limit=max_parser_entries,
                observed=source_edge_count,
                limits=limits,
            )
        if citation_count > max_citations:
            raise ReferenceIOLimitError(
                resource="citation occurrences",
                limit_name="max_candidates",
                limit=max_citations,
                observed=citation_count,
                limits=limits,
            )
        if mode is CitationScanMode.BUILD_GRAPH:
            selected_includes = set(include_only or ())
            for edge in reversed(parsed.edges):
                if edge.command == "include" and include_only is not None:
                    stem = edge.target_path.removesuffix(".tex")
                    if stem not in selected_includes:
                        continue
                if edge.target_path in visited:
                    continue
                if edge.target_path in queued:
                    continue
                target_depth = include_depth + 1
                if target_depth > max_include_depth:
                    raise ReferenceIOLimitError(
                        resource="citation source graph",
                        limit_name="max_nesting_depth",
                        limit=max_include_depth,
                        observed=target_depth,
                        limits=limits,
                    )
                pending.append((PurePosixPath(edge.target_path), target_depth))
                queued.add(edge.target_path)

    active_paths = tuple(sorted(visited))
    defined_commands = {
        command
        for parsed in parsed_by_path.values()
        for command in parsed.defined_commands
    }
    ambiguous_invocations = sorted(
        (command, locator)
        for parsed in parsed_by_path.values()
        for command, locator in parsed.unknown_invocations
        if command in defined_commands
    )
    if ambiguous_invocations:
        command, ambiguous_locator = ambiguous_invocations[0]
        raise _incomplete(
            "unsupported-command-definition",
            f"invocation of source-defined command \\{command} is unsupported",
            mode,
            normalized_entrypoint,
            parser_configuration,
            limits,
            source_locator=ambiguous_locator,
        )
    if mode is CitationScanMode.BUILD_GRAPH:
        cycle, graph_depth = _source_graph_analysis(
            parsed_by_path,
            active_paths=set(active_paths),
            include_only=include_only,
        )
        if cycle is not None:
            raise _incomplete(
                "cyclic-source-graph",
                "input/include graph contains a cycle",
                mode,
                normalized_entrypoint,
                parser_configuration,
                limits,
                source_locator=cycle,
            )
        if graph_depth > max_include_depth:
            raise ReferenceIOLimitError(
                resource="citation source graph",
                limit_name="max_nesting_depth",
                limit=max_include_depth,
                observed=graph_depth,
                limits=limits,
            )
    if mode is CitationScanMode.ALL_FILES_OBSERVATION:
        missing_targets = sorted(
            edge.target_path
            for parsed in parsed_by_path.values()
            for edge in parsed.edges
            if edge.target_path not in visited
        )
        if missing_targets:
            target = missing_targets[0]
            raise _incomplete(
                "include-target-unavailable",
                f"literal include target is unavailable: {target}",
                mode,
                normalized_entrypoint,
                parser_configuration,
                limits,
                source_locator=target,
            )

    use_map: dict[str, list[CitationLocator]] = defaultdict(list)
    source_graph: list[CitationSourceEdge] = []
    nocite_all = False
    for source_name in active_paths:
        parsed = parsed_by_path[source_name]
        for key, locator in parsed.uses:
            use_map[key].append(locator)
        source_graph.extend(parsed.edges)
        nocite_all = nocite_all or parsed.nocite_all
    cited = set(use_map)
    resolved = bibliography if nocite_all else cited & bibliography
    undefined = cited - bibliography
    uncited = set() if nocite_all else bibliography - cited

    source_identities = tuple(
        CitationSourceFile(
            relative_path=path,
            byte_size=len(raw_by_path[path]),
            sha256=hashlib.sha256(raw_by_path[path]).hexdigest(),
        )
        for path in active_paths
    )
    source_evidence = tuple(
        ContentEvidence.from_bytes(
            role="citation-source",
            filename=f"inputs/citation-source/{path}",
            content=raw_by_path[path],
        )
        for path in active_paths
    )
    uses = tuple(
        CitationUse(
            citekey=key,
            source_files=tuple(
                sorted({locator.source_path for locator in use_map[key]})
            ),
            locators=tuple(
                sorted(
                    set(use_map[key]),
                    key=lambda item: (
                        item.source_path,
                        item.line,
                        item.column,
                        item.command,
                    ),
                )
            ),
        )
        for key in sorted(use_map)
    )
    verified_source_tree = (
        _verify_source_tree(
            root,
            asserted_revision=source_revision,
            source_files=source_identities,
            limits=limits,
        )
        if storage_class is RootStorageClass.LOCAL
        else None
    )
    limitations = (
        "not-canonical-identity-acceptance",
        "not-contract-acceptance",
        "not-full-latex-semantics",
        "not-manuscript-acceptance",
        "not-publication-acceptance",
        "not-rights-clearance",
        "not-scientific-validation",
    )
    ordered_source_graph = tuple(
        sorted(
            source_graph,
            key=lambda item: (
                item.source_path,
                item.source_locator,
                item.command,
                item.target_path,
            ),
        )
    )
    fields: dict[str, object] = {
        "schema_version": CITATION_CLOSURE_SCHEMA_VERSION,
        "coverage_status": "complete",
        "authority_boundary": "citation-key-resolution-only",
        "limitations": limitations,
        "asserted_source_revision": source_revision,
        "root_preflight": root.preflight_evidence,
        "verified_source_tree": verified_source_tree,
        "mode": mode,
        "entrypoint": normalized_entrypoint,
        "parser_configuration": parser_configuration,
        "parser_configuration_id": parser_configuration.configuration_id,
        "effective_limits": limits,
        "effective_limits_id": limits.evidence_id,
        "bibliography_keys": tuple(sorted(bibliography)),
        "explicit_uses": uses,
        "cited_and_defined": tuple(sorted(resolved)),
        "cited_but_undefined": tuple(sorted(undefined)),
        "defined_but_uncited": tuple(sorted(uncited)),
        "nocite_all": nocite_all,
        "include_only": include_only,
        "source_graph": ordered_source_graph,
        "source_files": active_paths,
        "source_file_identities": source_identities,
        "source_file_evidence": source_evidence,
    }
    return CitationClosure(
        schema_version=CITATION_CLOSURE_SCHEMA_VERSION,
        coverage_status="complete",
        authority_boundary="citation-key-resolution-only",
        limitations=limitations,
        asserted_source_revision=source_revision,
        root_preflight=root.preflight_evidence,
        verified_source_tree=verified_source_tree,
        mode=mode,
        entrypoint=normalized_entrypoint,
        parser_configuration=parser_configuration,
        parser_configuration_id=parser_configuration.configuration_id,
        effective_limits=limits,
        effective_limits_id=limits.evidence_id,
        bibliography_keys=tuple(sorted(bibliography)),
        explicit_uses=uses,
        cited_and_defined=tuple(sorted(resolved)),
        cited_but_undefined=tuple(sorted(undefined)),
        defined_but_uncited=tuple(sorted(uncited)),
        nocite_all=nocite_all,
        include_only=include_only,
        source_graph=ordered_source_graph,
        source_files=active_paths,
        source_file_identities=source_identities,
        source_file_evidence=source_evidence,
        closure_id=_stable_id("citation-closure", fields),
    )


def _source_graph_analysis(
    parsed_by_path: dict[str, _ParsedFile],
    *,
    active_paths: set[str],
    include_only: tuple[str, ...] | None,
) -> tuple[str | None, int]:
    selected_includes = set(include_only or ())
    adjacency: dict[str, set[str]] = {path: set() for path in active_paths}
    indegree = {path: 0 for path in active_paths}
    for source, parsed in parsed_by_path.items():
        for edge in parsed.edges:
            if edge.target_path not in active_paths:
                continue
            if edge.command == "include" and include_only is not None:
                if (
                    edge.target_path.removesuffix(".tex")
                    not in selected_includes
                ):
                    continue
            if edge.target_path not in adjacency[source]:
                adjacency[source].add(edge.target_path)
                indegree[edge.target_path] += 1
    ready = [path for path, count in indegree.items() if count == 0]
    heapq.heapify(ready)
    depth = {path: 0 for path in active_paths}
    consumed = 0
    while ready:
        source = heapq.heappop(ready)
        consumed += 1
        for target in sorted(adjacency[source]):
            depth[target] = max(depth[target], depth[source] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready, target)
    if consumed == len(active_paths):
        return None, max(depth.values(), default=0)
    cycle = sorted(path for path, count in indegree.items() if count > 0)[0]
    return cycle, 0


def _parse_source(
    text: str,
    *,
    source_path: str,
    configuration: CitationParserConfiguration,
    limits: ReferenceIOLimits,
    citations_observed: int,
) -> _ParsedFile:
    uses: list[tuple[str, CitationLocator]] = []
    edges: list[CitationSourceEdge] = []
    defined_commands: list[str] = []
    unknown_invocations: list[tuple[str, str]] = []
    nocite_all = False
    include_only: tuple[str, ...] | None = None
    aliases = dict(configuration.aliases)
    singular = set(configuration.citation_commands)
    multicite = set(configuration.multicite_commands)
    includes = set(configuration.include_commands)
    i = 0
    tokens = 0
    max_tokens = _required_limit(limits.max_entries, "max_entries")
    max_keys = _required_limit(limits.max_candidates, "max_candidates")
    while i < len(text):
        character = text[i]
        if character == "%" and not _is_escaped(text, i):
            newline = text.find("\n", i)
            i = len(text) if newline < 0 else newline + 1
            continue
        if character != "\\":
            i += 1
            continue
        start = i
        command, i = _command_name(text, i)
        if not command:
            continue
        tokens += 1
        if tokens > max_tokens:
            raise _ParseFailure(
                "parser-token-limit",
                "citation parser token limit was exceeded",
                start,
            )
        starred = False
        if i < len(text) and text[i] == "*":
            starred = True
            i += 1
        if command in {"verb", "Verb"}:
            i = _skip_verb(text, i, start)
            continue
        if command == "begin":
            if starred:
                raise _ParseFailure(
                    "unsupported-starred-command",
                    "starred begin is outside the parser contract",
                    start,
                )
            position = _skip_space(text, i)
            environment, end = _literal_group(
                text,
                position,
                configuration.max_group_depth,
                start,
            )
            if environment in configuration.verbatim_environments:
                marker = f"\\end{{{environment}}}"
                close = text.find(marker, end)
                if close < 0:
                    raise _ParseFailure(
                        "unterminated-verbatim-region",
                        f"unterminated verbatim-like environment {environment}",
                        start,
                    )
                i = close + len(marker)
                continue
            i = end
            continue
        if command in {"newcommand", "renewcommand", "providecommand"}:
            i, defined_command = _skip_newcommand(text, i, configuration, start)
            if defined_command in (
                singular
                | multicite
                | includes
                | {"Verb", "begin", "includeonly", "nocite", "verb"}
            ):
                raise _ParseFailure(
                    "unsupported-command-definition",
                    "redefinition of a parser-recognized command is "
                    "unsupported",
                    start,
                )
            defined_commands.append(defined_command)
            continue
        if command in (
            _UNSUPPORTED_DEFINITION_COMMANDS
            | {"def", "edef", "gdef", "let", "xdef"}
        ):
            raise _ParseFailure(
                "unsupported-command-definition",
                f"unsupported TeX command definition \\{command}",
                start,
            )
        if command == "includeonly":
            if starred:
                raise _ParseFailure(
                    "unsupported-starred-command",
                    "starred includeonly is outside the parser contract",
                    start,
                )
            if include_only is not None:
                raise _ParseFailure(
                    "ambiguous-includeonly",
                    "multiple includeonly declarations are unsupported",
                    start,
                )
            raw, i = _literal_group(
                text,
                _skip_space(text, i),
                configuration.max_group_depth,
                start,
            )
            values: list[str] = []
            for target in raw.split(","):
                cleaned = target.strip()
                if not cleaned:
                    raise _ParseFailure(
                        "ambiguous-includeonly",
                        "includeonly contains an empty target",
                        start,
                    )
                values.append(
                    _resolve_source_target(
                        source_path,
                        cleaned,
                        start,
                    ).removesuffix(".tex")
                )
            include_only = tuple(sorted(set(values)))
            continue
        if command in includes:
            if starred:
                raise _ParseFailure(
                    "unsupported-include-syntax",
                    f"starred \\{command} is unsupported",
                    start,
                )
            raw_target, i = _literal_group(
                text,
                _skip_space(text, i),
                configuration.max_group_depth,
                start,
            )
            target = _resolve_source_target(source_path, raw_target, start)
            line, column = _line_column(text, start)
            edges.append(
                CitationSourceEdge(
                    command=command,
                    source_path=source_path,
                    target_path=target,
                    source_locator=f"{source_path}:{line}:{column}",
                )
            )
            continue
        canonical = aliases.get(command, command)
        if canonical in singular or canonical == "nocite":
            if starred:
                raise _ParseFailure(
                    "unsupported-starred-command",
                    "starred citation commands are outside the parser contract",
                    start,
                )
            key_groups, i = _citation_arguments(
                text,
                i,
                start,
                configuration,
                multiple=False,
                max_groups=None,
                limits=limits,
            )
        elif canonical in multicite:
            if starred:
                raise _ParseFailure(
                    "unsupported-starred-command",
                    "starred citation commands are outside the parser contract",
                    start,
                )
            key_groups, i = _citation_arguments(
                text,
                i,
                start,
                configuration,
                multiple=True,
                max_groups=max_keys - citations_observed - len(uses),
                limits=limits,
            )
        else:
            lowered = command.lower()
            if (
                "cite" in lowered
                or command
                in {
                    "InputIfFileExists",
                    "import",
                    "includefrom",
                    "inputfrom",
                    "subfile",
                    "subimport",
                }
                or lowered.startswith("if")
                or command in {"else", "fi", "csname"}
            ):
                raise _ParseFailure(
                    "unsupported-or-ambiguous-syntax",
                    f"unsupported or ambiguous TeX command \\{command}",
                    start,
                )
            line, column = _line_column(text, start)
            unknown_invocations.append(
                (command, f"{source_path}:{line}:{column}")
            )
            continue
        line, column = _line_column(text, start)
        observed_command = command + ("*" if starred else "")
        locator = CitationLocator(
            source_path=source_path,
            line=line,
            column=column,
            command=observed_command,
        )
        for group in key_groups:
            keys = _parse_keys(
                group,
                canonical,
                start,
                max_keys=max_keys,
                citations_observed=citations_observed + len(uses),
                limits=limits,
            )
            for key in keys:
                if key == "*":
                    nocite_all = True
                else:
                    uses.append((key, locator))
    return _ParsedFile(
        uses=tuple(uses),
        edges=tuple(edges),
        nocite_all=nocite_all,
        include_only=include_only,
        token_count=tokens,
        defined_commands=tuple(sorted(set(defined_commands))),
        unknown_invocations=tuple(unknown_invocations),
    )


def _citation_arguments(
    text: str,
    position: int,
    start: int,
    configuration: CitationParserConfiguration,
    *,
    multiple: bool,
    max_groups: int | None,
    limits: ReferenceIOLimits,
) -> tuple[tuple[str, ...], int]:
    groups: list[str] = []
    cursor = position
    while True:
        cursor = _skip_space(text, cursor)
        if max_groups is not None and len(groups) >= max_groups:
            limit = _required_limit(limits.max_candidates, "max_candidates")
            raise ReferenceIOLimitError(
                resource="citation occurrences",
                limit_name="max_candidates",
                limit=limit,
                observed=limit + 1,
                limits=limits,
            )
        optional_count = 0
        while cursor < len(text) and text[cursor] == "[":
            optional, cursor = _balanced_group(
                text,
                cursor,
                "[",
                "]",
                configuration.max_group_depth,
                start,
            )
            if "\\" in optional:
                raise _ParseFailure(
                    "nonliteral-optional-argument",
                    "citation optional arguments cannot contain TeX controls",
                    start,
                )
            optional_count += 1
            if optional_count > configuration.max_optional_arguments:
                raise _ParseFailure(
                    "too-many-optional-arguments",
                    "citation command exceeds the optional-argument contract",
                    start,
                )
            cursor = _skip_space(text, cursor)
        if cursor >= len(text) or text[cursor] != "{":
            if groups and multiple:
                break
            raise _ParseFailure(
                "malformed-citation-command",
                "citation command lacks a literal citekey group",
                start,
            )
        group, cursor = _balanced_group(
            text,
            cursor,
            "{",
            "}",
            configuration.max_group_depth,
            start,
        )
        groups.append(group)
        if not multiple:
            break
        lookahead = _skip_space(text, cursor)
        if lookahead >= len(text) or text[lookahead] not in "[{":
            break
        cursor = lookahead
    return tuple(groups), cursor


def _parse_keys(
    group: str,
    command: str,
    start: int,
    *,
    max_keys: int,
    citations_observed: int,
    limits: ReferenceIOLimits,
) -> tuple[str, ...]:
    if any(character in group for character in "{}\\%"):
        raise _ParseFailure(
            "nonliteral-citekey",
            "citation key group contains unsupported TeX syntax",
            start,
        )
    keys: list[str] = []
    cursor = 0
    raw_count = 0
    citation_count = 0
    while True:
        separator = group.find(",", cursor)
        end = len(group) if separator < 0 else separator
        raw_count += 1
        if raw_count > max_keys:
            raise _ParseFailure(
                "citation-key-limit",
                "citation command exceeds the key-count contract",
                start,
            )
        key = group[cursor:end].strip()
        if not key:
            raise _ParseFailure(
                "empty-citekey",
                "citation key group contains an empty key",
                start,
            )
        if key == "*":
            if command != "nocite":
                raise _ParseFailure(
                    "unsupported-wildcard-citation",
                    "the * wildcard is supported only by nocite",
                    start,
                )
            keys.append(key)
        else:
            observed = citations_observed + citation_count + 1
            if observed > max_keys:
                raise ReferenceIOLimitError(
                    resource="citation occurrences",
                    limit_name="max_candidates",
                    limit=max_keys,
                    observed=observed,
                    limits=limits,
                )
            try:
                keys.append(validate_citekey(key, field="citation key"))
            except PathSafetyError as error:
                raise _ParseFailure(
                    "invalid-citekey",
                    "citation key is outside the supported portable syntax",
                    start,
                ) from error
            citation_count += 1
        if separator < 0:
            break
        cursor = separator + 1
    return tuple(keys)


def _skip_newcommand(
    text: str,
    position: int,
    configuration: CitationParserConfiguration,
    start: int,
) -> tuple[int, str]:
    cursor = _skip_space(text, position)
    if cursor < len(text) and text[cursor] == "*":
        cursor = _skip_space(text, cursor + 1)
    macro_name, cursor = _balanced_group(
        text,
        cursor,
        "{",
        "}",
        configuration.max_group_depth,
        start,
    )
    if re.fullmatch(r"\\[A-Za-z@]+", macro_name) is None:
        raise _ParseFailure(
            "unsupported-command-definition",
            "newcommand name is outside the supported literal syntax",
            start,
        )
    for _ in range(2):
        cursor = _skip_space(text, cursor)
        if cursor < len(text) and text[cursor] == "[":
            _, cursor = _balanced_group(
                text,
                cursor,
                "[",
                "]",
                configuration.max_group_depth,
                start,
            )
    cursor = _skip_space(text, cursor)
    _, cursor = _balanced_group(
        text,
        cursor,
        "{",
        "}",
        configuration.max_group_depth,
        start,
    )
    return cursor, macro_name.removeprefix("\\")


def _literal_group(
    text: str, position: int, max_depth: int, start: int
) -> tuple[str, int]:
    if position >= len(text) or text[position] != "{":
        raise _ParseFailure(
            "nonliteral-required-argument",
            "supported command requires a literal braced argument",
            start,
        )
    value, end = _balanced_group(text, position, "{", "}", max_depth, start)
    if any(character in value for character in "{}\\%"):
        raise _ParseFailure(
            "nonliteral-required-argument",
            "required argument contains unsupported TeX syntax",
            start,
        )
    return value.strip(), end


def _balanced_group(
    text: str,
    position: int,
    opener: str,
    closer: str,
    max_depth: int,
    start: int,
) -> tuple[str, int]:
    if position >= len(text) or text[position] != opener:
        raise _ParseFailure(
            "malformed-group", "expected a delimited group", start
        )
    depth = 1
    i = position + 1
    value: list[str] = []
    while i < len(text):
        character = text[i]
        escaped = _is_escaped(text, i)
        if character == "%" and not escaped:
            newline = text.find("\n", i)
            i = len(text) if newline < 0 else newline + 1
            continue
        if character == opener and not escaped:
            depth += 1
            if depth > max_depth:
                raise _ParseFailure(
                    "group-depth-limit",
                    "TeX group exceeds the parser depth contract",
                    start,
                )
            value.append(character)
        elif character == closer and not escaped:
            depth -= 1
            if depth == 0:
                return "".join(value), i + 1
            value.append(character)
        else:
            value.append(character)
        i += 1
    raise _ParseFailure("unterminated-group", "unterminated TeX group", start)


def _skip_verb(text: str, position: int, start: int) -> int:
    if position >= len(text) or text[position].isspace():
        raise _ParseFailure(
            "malformed-verbatim-command", "verb requires a delimiter", start
        )
    delimiter = text[position]
    end = text.find(delimiter, position + 1)
    if end < 0 or "\n" in text[position + 1 : end]:
        raise _ParseFailure(
            "unterminated-verbatim-command", "unterminated verb command", start
        )
    return end + 1


def _command_name(text: str, position: int) -> tuple[str, int]:
    i = position + 1
    if i >= len(text):
        return "", i
    if not (text[i].isalpha() or text[i] == "@"):
        return text[i], i + 1
    start = i
    while i < len(text) and (text[i].isalpha() or text[i] == "@"):
        i += 1
    return text[start:i], i


def _resolve_source_target(
    source_path: str, raw_target: str, start: int
) -> str:
    del source_path
    target = raw_target.strip()
    if (
        not target
        or target.startswith("/")
        or "\\" in target
        or "\x00" in target
        or any(character in target for character in "{}%")
    ):
        raise _ParseFailure(
            "unsafe-include-target",
            "include target is not a literal confined relative path",
            start,
        )
    if PurePosixPath(target).suffix == "":
        target += ".tex"
    elif PurePosixPath(target).suffix != ".tex":
        raise _ParseFailure(
            "unsupported-include-target",
            "only TeX include targets are supported",
            start,
        )
    combined = posixpath.normpath(target)
    if (
        combined == ".."
        or combined.startswith("../")
        or combined.startswith("/")
    ):
        raise _ParseFailure(
            "include-target-escapes-root",
            "include target escapes the declared manuscript root",
            start,
        )
    try:
        return validate_relative_path(
            combined, field="include target"
        ).as_posix()
    except PathSafetyError as error:
        raise _ParseFailure(
            "unsafe-include-target",
            "include target is not a portable relative path",
            start,
        ) from error


def _source_path(value: str) -> PurePosixPath:
    path = validate_relative_path(value, field="citation entrypoint")
    if path.suffix == "":
        path = PurePosixPath(path.as_posix() + ".tex")
    if path.suffix != ".tex":
        raise ValueError("citation entrypoint must be a TeX source")
    return path


def _is_escaped(text: str, position: int) -> bool:
    slashes = 0
    cursor = position - 1
    while cursor >= 0 and text[cursor] == "\\":
        slashes += 1
        cursor -= 1
    return slashes % 2 == 1


def _skip_space(text: str, position: int) -> int:
    while position < len(text):
        if text[position].isspace():
            position += 1
            continue
        if text[position] == "%" and not _is_escaped(text, position):
            newline = text.find("\n", position)
            position = len(text) if newline < 0 else newline + 1
            continue
        break
    return position


def _line_column(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    previous = text.rfind("\n", 0, offset)
    column = offset + 1 if previous < 0 else offset - previous
    return line, column


def _stable_id(kind: str, value: object) -> str:
    digest = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    return f"{kind}:sha256:{digest}"


def _required_limit(value: int | None, name: str) -> int:
    if value is None:
        raise ValueError(f"citation I/O profile must define {name}")
    return value


def _limit_error(
    error: PathLimitError, limits: ReferenceIOLimits
) -> ReferenceIOLimitError:
    return ReferenceIOLimitError(
        resource=error.resource,
        limit_name=error.limit_name,
        limit=error.limit,
        observed=error.observed,
        limits=limits,
    )


def _incomplete(
    reason_code: str,
    message: str,
    mode: CitationScanMode,
    entrypoint: str | None,
    parser_configuration: CitationParserConfiguration,
    limits: ReferenceIOLimits,
    *,
    source_locator: str | None = None,
) -> CitationCoverageIncomplete:
    return CitationCoverageIncomplete(
        reason_code=reason_code,
        message=message,
        mode=mode,
        entrypoint=entrypoint,
        parser_configuration=parser_configuration,
        limits=limits,
        source_locator=source_locator,
    )


def _verify_source_tree(
    root: AuthorizedRoot,
    *,
    asserted_revision: str,
    source_files: tuple[CitationSourceFile, ...],
    limits: ReferenceIOLimits,
) -> VerifiedSourceTree | None:
    if (
        re.fullmatch(r"[0-9a-f]{40,64}", asserted_revision) is None
        or not source_files
    ):
        return None

    git_cwd = root.path

    def git_bytes(*arguments: str) -> bytes:
        completed = subprocess.run(
            ("git", "-C", str(git_cwd), *arguments),
            check=True,
            capture_output=True,
            timeout=30,
        )
        return completed.stdout

    def git_text(*arguments: str) -> str:
        return git_bytes(*arguments).decode("utf-8").strip()

    try:
        root.state(source_files[0].relative_path)
        repository_root = Path(git_text("rev-parse", "--show-toplevel"))
        repository_root = repository_root.resolve(strict=True)
        source_prefix = root.path.resolve(strict=True).relative_to(
            repository_root
        )
        git_cwd = repository_root
        head = git_text("rev-parse", "HEAD")
        if head != asserted_revision:
            return None
        if not _git_status_is_clean(
            git_cwd,
            max_bytes=_required_limit(
                limits.max_text_total_bytes, "max_text_total_bytes"
            ),
            max_entries=_required_limit(limits.max_entries, "max_entries"),
            max_entry_bytes=_required_limit(
                limits.max_text_bytes, "max_text_bytes"
            ),
        ):
            return None
        for source in source_files:
            repository_path = (
                source_prefix / PurePosixPath(source.relative_path)
            ).as_posix()
            listing = git_bytes(
                "ls-tree",
                "-z",
                head,
                "--",
                f":(top){repository_path}",
            )
            records = tuple(item for item in listing.split(b"\x00") if item)
            if len(records) != 1:
                return None
            metadata, separator, listed_path = records[0].partition(b"\t")
            parts = metadata.split()
            if (
                not separator
                or len(parts) != 3
                or parts[0] not in {b"100644", b"100755"}
                or parts[1] != b"blob"
                or listed_path.decode("utf-8") != repository_path
            ):
                return None
            object_id = parts[2].decode("ascii")
            object_size = int(git_text("cat-file", "-s", object_id))
            if object_size != source.byte_size:
                return None
            blob = git_bytes("cat-file", "blob", object_id)
            if (
                len(blob) != source.byte_size
                or hashlib.sha256(blob).hexdigest() != source.sha256
            ):
                return None
        tree_id = git_text("rev-parse", f"{head}^{{tree}}")
        if git_text("rev-parse", "HEAD") != head:
            return None
        if not _git_status_is_clean(
            git_cwd,
            max_bytes=_required_limit(
                limits.max_text_total_bytes, "max_text_total_bytes"
            ),
            max_entries=_required_limit(limits.max_entries, "max_entries"),
            max_entry_bytes=_required_limit(
                limits.max_text_bytes, "max_text_bytes"
            ),
        ):
            return None
        root.state(source_files[0].relative_path)
    except (
        FileNotFoundError,
        OSError,
        subprocess.SubprocessError,
        TimeoutError,
        UnicodeError,
        ValueError,
        _GitProbeError,
    ):
        return None
    return VerifiedSourceTree(
        commit_id=head,
        tree_id=tree_id,
        verification_method="git-clean-head",
    )


def _git_status_is_clean(
    repository_root: Path,
    *,
    max_bytes: int,
    max_entries: int,
    max_entry_bytes: int,
    timeout_seconds: float = _GIT_STATUS_TIMEOUT_SECONDS,
) -> bool:
    """Stream a complete porcelain status under hard evidence bounds."""
    for name, value in (
        ("max_bytes", max_bytes),
        ("max_entries", max_entries),
        ("max_entry_bytes", max_entry_bytes),
    ):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    try:
        process = subprocess.Popen(
            (
                "git",
                "-C",
                str(repository_root),
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        raise _GitProbeError("cannot start bounded Git status probe") from error
    stream = process.stdout
    if stream is None:
        process.kill()
        process.wait()
        raise _GitProbeError("Git status probe has no output stream")
    selector = selectors.DefaultSelector()
    deadline = time.monotonic() + timeout_seconds
    total_bytes = 0
    entries = 0
    entry_bytes = 0
    try:
        selector.register(stream, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise _GitProbeError("Git status probe timed out")
            chunk = os.read(
                stream.fileno(),
                min(
                    _GIT_STATUS_CHUNK_BYTES,
                    max_bytes - total_bytes + 1,
                ),
            )
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                raise _GitProbeError("Git status byte limit exceeded")
            fields = chunk.split(b"\x00")
            entry_bytes += len(fields[0])
            if entry_bytes > max_entry_bytes:
                raise _GitProbeError("Git status entry byte limit exceeded")
            for field in fields[1:]:
                entries += 1
                if entries > max_entries:
                    raise _GitProbeError("Git status entry limit exceeded")
                entry_bytes = len(field)
                if entry_bytes > max_entry_bytes:
                    raise _GitProbeError("Git status entry byte limit exceeded")
        if entry_bytes:
            raise _GitProbeError("Git status output is not NUL-terminated")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _GitProbeError("Git status probe timed out")
        try:
            return_code = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as error:
            raise _GitProbeError("Git status probe timed out") from error
        if return_code != 0:
            raise _GitProbeError("Git status probe command failed")
        return total_bytes == 0
    except (OSError, ValueError) as error:
        raise _GitProbeError("Git status probe failed") from error
    finally:
        selector.close()
        stream.close()
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=1)
            except subprocess.SubprocessError:
                pass
