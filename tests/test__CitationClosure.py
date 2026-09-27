from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import projectkoios.references.citation_closure as citation_closure_module
import pytest
from projectkoios.references.citation_closure import (
    CITATION_CLOSURE_SCHEMA_VERSION,
    DEFAULT_CITATION_PARSER_CONFIGURATION,
    CitationCoverageIncomplete,
    CitationParserConfiguration,
    CitationScanMode,
    build_citation_closure,
)
from projectkoios.references.cli import main
from projectkoios.references.io_limits import (
    RECONCILIATION_IO_LIMITS,
    ReferenceIOLimitError,
)
from projectkoios.references.path_safety import RootStorageClass


def _build(
    root: Path,
    *,
    keys: tuple[str, ...],
    entrypoint: str = "main.tex",
    revision: str = "asserted-fixture-revision",
    configuration: CitationParserConfiguration = (
        DEFAULT_CITATION_PARSER_CONFIGURATION
    ),
):  # type: ignore[no-untyped-def]
    return build_citation_closure(
        root,
        storage_class=RootStorageClass.LOCAL,
        mode=CitationScanMode.BUILD_GRAPH,
        entrypoint=entrypoint,
        bibliography_keys=keys,
        source_revision=revision,
        parser_configuration=configuration,
    )


def test__citation_parser_configuration__rejects_non_control_word_names() -> (
    None
):
    with pytest.raises(ValueError, match="citation aliases"):
        CitationParserConfiguration(aliases=(("foo2", "cite"),))

    commands = tuple(
        sorted(
            (*DEFAULT_CITATION_PARSER_CONFIGURATION.citation_commands, "cite2")
        )
    )
    with pytest.raises(ValueError, match="command sets"):
        replace(
            DEFAULT_CITATION_PARSER_CONFIGURATION,
            citation_commands=commands,
        )


def test__citation_closure__resolves_explicit_bounded_build_graph(
    tmp_path: Path,
) -> None:
    root = tmp_path / "synthetic-manuscript"
    (root / "chapters").mkdir(parents=True)
    (root / "shared").mkdir()
    (root / "main.tex").write_text(
        r"""
\includeonly{chapters/active}
\cite[see][p. 1]{alpha,beta}
\cites[before][after]{gamma}[note]{delta}
\fixturecite{epsilon}
\nocite{*}
% \cite{commented}
\verb|\cite{inlineVerb}|
\begin{verbatim}
\cite{blockVerb}
\end{verbatim}
\include{chapters/active}
\include{chapters/inactive}
\input{shared/literal}
""",
        encoding="utf-8",
    )
    (root / "chapters" / "active.tex").write_text(
        "\\textcite{zeta}\n", encoding="utf-8"
    )
    (root / "chapters" / "inactive.tex").write_text(
        "\\cite{inactive}\n", encoding="utf-8"
    )
    (root / "shared" / "literal.tex").write_text(
        "\\autocite{eta}\n", encoding="utf-8"
    )
    (root / "template.tex").write_text("\\cite{template}\n", encoding="utf-8")
    configuration = replace(
        DEFAULT_CITATION_PARSER_CONFIGURATION,
        aliases=(("fixturecite", "cite"),),
    )
    bibliography = (
        "alpha",
        "beta",
        "delta",
        "epsilon",
        "eta",
        "gamma",
        "uncitedButNocited",
        "zeta",
    )

    closure = _build(root, keys=bibliography, configuration=configuration)

    assert closure.schema_version == CITATION_CLOSURE_SCHEMA_VERSION == 5
    assert closure.coverage_status == "complete"
    assert closure.authority_boundary == "citation-key-resolution-only"
    assert closure.mode is CitationScanMode.BUILD_GRAPH
    assert closure.entrypoint == "main.tex"
    assert closure.source_files == (
        "chapters/active.tex",
        "main.tex",
        "shared/literal.tex",
    )
    assert closure.include_only == ("chapters/active",)
    assert closure.nocite_all
    assert closure.cited_and_defined == tuple(sorted(bibliography))
    assert closure.cited_but_undefined == ()
    assert closure.defined_but_uncited == ()
    assert {item.citekey for item in closure.explicit_uses} == {
        "alpha",
        "beta",
        "delta",
        "epsilon",
        "eta",
        "gamma",
        "zeta",
    }
    assert all(
        not locator.source_path.startswith("/")
        for use in closure.explicit_uses
        for locator in use.locators
    )
    rendered = closure.to_json()
    assert str(tmp_path) not in rendered
    assert "inlineVerb" not in rendered
    assert "blockVerb" not in rendered
    assert "commented" not in rendered
    assert "template" not in rendered
    assert "not-full-latex-semantics" in rendered


def test__citation_closure__inactive_files_do_not_change_build_identity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "manuscript"
    root.mkdir()
    (root / "main.tex").write_text(
        "\\input{active}\n\\cite{alpha}\n", encoding="utf-8"
    )
    active = root / "active.tex"
    active.write_text("Synthetic prose.\n", encoding="utf-8")
    inactive = root / "template.tex"
    inactive.write_text("\\cite{template}\n", encoding="utf-8")

    baseline = _build(root, keys=("alpha",))
    inactive.write_text("\\cite{differentTemplate}\n", encoding="utf-8")
    unchanged = _build(root, keys=("alpha",))
    assert unchanged.closure_id == baseline.closure_id

    active.write_text("Different synthetic prose.\n", encoding="utf-8")
    changed = _build(root, keys=("alpha",))
    assert changed.closure_id != baseline.closure_id
    assert changed.source_file_identities != baseline.source_file_identities

    revised = _build(root, keys=("alpha",), revision="other-revision")
    assert revised.closure_id != changed.closure_id


def test__citation_closure__all_files_mode_is_explicit_and_distinct(
    tmp_path: Path,
) -> None:
    root = tmp_path / "manuscript"
    root.mkdir()
    (root / "main.tex").write_text("\\cite{alpha}\n", encoding="utf-8")
    (root / "template.tex").write_text("\\cite{template}\n", encoding="utf-8")

    observed = build_citation_closure(
        root,
        storage_class=RootStorageClass.LOCAL,
        mode=CitationScanMode.ALL_FILES_OBSERVATION,
        entrypoint=None,
        bibliography_keys=("alpha", "template"),
        source_revision="fixture",
    )

    assert observed.entrypoint is None
    assert observed.source_files == ("main.tex", "template.tex")
    assert observed.cited_and_defined == ("alpha", "template")
    with pytest.raises(ValueError, match="forbids an entrypoint"):
        build_citation_closure(
            root,
            storage_class=RootStorageClass.LOCAL,
            mode=CitationScanMode.ALL_FILES_OBSERVATION,
            entrypoint="main.tex",
            bibliography_keys=("alpha",),
            source_revision="fixture",
        )


@pytest.mark.parametrize(
    ("source", "reason"),
    (
        ("\\unknowncite{alpha}\n", "unsupported-or-ambiguous-syntax"),
        ("\\input{\\jobname-part}\n", "nonliteral-required-argument"),
        (
            "\\newcommand{\\foo}[1]{\\cite{#1}}\n\\foo{alpha}\n",
            "unsupported-command-definition",
        ),
        (
            "\\DeclareRobustCommand{\\foo}[1]{Synthetic #1}\n\\foo{alpha}\n",
            "unsupported-command-definition",
        ),
        (
            "\\NewDocumentCommand{\\foo}{m}{Synthetic #1}\n\\foo{alpha}\n",
            "unsupported-command-definition",
        ),
        ("\\cite[see \\cite{beta}]{alpha}\n", "nonliteral-optional-argument"),
        ("\\cite{alpha,{beta}}\n", "nonliteral-citekey"),
        ("\\ifdraft\\cite{alpha}\\fi\n", "unsupported-or-ambiguous-syntax"),
        ("\\begin{verbatim}\\cite{alpha}\n", "unterminated-verbatim-region"),
        (
            "\\begin*{verbatim}\\cite{alpha}\\end{verbatim}\n",
            "unsupported-starred-command",
        ),
    ),
)
def test__citation_closure__unsupported_syntax_is_typed_incomplete(
    tmp_path: Path,
    source: str,
    reason: str,
) -> None:
    root = tmp_path / reason
    root.mkdir()
    (root / "main.tex").write_text(source, encoding="utf-8")

    with pytest.raises(CitationCoverageIncomplete) as raised:
        _build(root, keys=("alpha",))

    assert raised.value.coverage_status == "incomplete"
    assert raised.value.reason_code == reason
    report = raised.value.to_dict()
    assert report["coverage_status"] == "incomplete"
    assert report["parser_configuration_id"]
    assert str(tmp_path) not in raised.value.to_json()


def test__citation_closure__configured_alias_can_name_a_source_macro(
    tmp_path: Path,
) -> None:
    root = tmp_path / "configured-source-macro"
    root.mkdir()
    (root / "main.tex").write_text(
        "\\newcommand{\\fixturecite}[1]{\\cite{#1}}\n\\fixturecite{alpha}\n",
        encoding="utf-8",
    )
    configuration = replace(
        DEFAULT_CITATION_PARSER_CONFIGURATION,
        aliases=(("fixturecite", "cite"),),
    )

    closure = _build(root, keys=("alpha",), configuration=configuration)

    assert closure.cited_and_defined == ("alpha",)


def test__citation_closure__comments_inside_key_groups_are_skipped(
    tmp_path: Path,
) -> None:
    root = tmp_path / "commented-key"
    root.mkdir()
    (root / "main.tex").write_text(
        "\\cite{alpha% synthetic comment\n}\n", encoding="utf-8"
    )

    closure = _build(root, keys=("alpha",))

    assert closure.cited_and_defined == ("alpha",)


def test__citation_closure__missing_and_cyclic_build_graphs_are_incomplete(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"
    missing.mkdir()
    (missing / "main.tex").write_text("\\input{absent}\n", encoding="utf-8")
    with pytest.raises(CitationCoverageIncomplete) as absent:
        _build(missing, keys=("alpha",))
    assert absent.value.reason_code == "source-unavailable"

    cyclic = tmp_path / "cyclic"
    cyclic.mkdir()
    (cyclic / "main.tex").write_text("\\input{part}\n", encoding="utf-8")
    (cyclic / "part.tex").write_text("\\input{main}\n", encoding="utf-8")
    with pytest.raises(CitationCoverageIncomplete) as cycle:
        _build(cyclic, keys=("alpha",))
    assert cycle.value.reason_code == "cyclic-source-graph"


def test__citation_closure__enforces_longest_build_graph_depth(
    tmp_path: Path,
) -> None:
    root = tmp_path / "deep-graph"
    root.mkdir()
    (root / "main.tex").write_text("\\input{a}\\input{b}\n", encoding="utf-8")
    (root / "a.tex").write_text("\\input{b}\n", encoding="utf-8")
    (root / "b.tex").write_text("Synthetic leaf.\n", encoding="utf-8")
    limits = replace(RECONCILIATION_IO_LIMITS, max_nesting_depth=1)

    with pytest.raises(ReferenceIOLimitError) as raised:
        build_citation_closure(
            root,
            storage_class=RootStorageClass.LOCAL,
            mode=CitationScanMode.BUILD_GRAPH,
            entrypoint="main.tex",
            bibliography_keys=("alpha",),
            source_revision="fixture",
            limits=limits,
        )

    assert raised.value.limit_name == "max_nesting_depth"
    assert raised.value.observed == 2


def test__citation_closure__parser_token_limit_is_operation_wide(
    tmp_path: Path,
) -> None:
    root = tmp_path / "token-limit"
    root.mkdir()
    (root / "main.tex").write_text("\\input{part}\n", encoding="utf-8")
    (root / "part.tex").write_text(
        "\\cite{alpha}\\cite{beta}\n", encoding="utf-8"
    )
    limits = replace(RECONCILIATION_IO_LIMITS, max_entries=2)

    with pytest.raises(ReferenceIOLimitError) as raised:
        build_citation_closure(
            root,
            storage_class=RootStorageClass.LOCAL,
            mode=CitationScanMode.BUILD_GRAPH,
            entrypoint="main.tex",
            bibliography_keys=("alpha", "beta"),
            source_revision="fixture",
            limits=limits,
        )

    assert raised.value.resource == "citation parser tokens"
    assert raised.value.observed == 3


def test__citation_closure__moving_head_cannot_mix_git_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "moving-head"
    manuscript = repository / "manuscript"
    manuscript.mkdir(parents=True)
    (manuscript / "main.tex").write_text("\\cite{alpha}\n", encoding="utf-8")
    marker = repository / "marker.txt"
    marker.write_text("first\n", encoding="utf-8")
    subprocess.run(("git", "init", "-q"), cwd=repository, check=True)
    subprocess.run(("git", "add", "."), cwd=repository, check=True)
    for label in ("first", "second"):
        if label == "second":
            marker.write_text("second\n", encoding="utf-8")
            subprocess.run(("git", "add", "."), cwd=repository, check=True)
        subprocess.run(
            (
                "git",
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                label,
            ),
            cwd=repository,
            check=True,
        )
    second = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    first = subprocess.run(
        ("git", "rev-parse", "HEAD^"),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ("git", "reset", "--hard", first),
        cwd=repository,
        check=True,
        capture_output=True,
    )
    real_run = subprocess.run
    moved = False

    def moving_run(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        nonlocal moved
        command = args[0]
        if not moved and "ls-tree" in command:
            real_run(
                ("git", "reset", "--hard", second),
                cwd=repository,
                check=True,
                capture_output=True,
            )
            moved = True
        return real_run(*args, **kwargs)

    monkeypatch.setattr(citation_closure_module.subprocess, "run", moving_run)

    closure = _build(root=manuscript, keys=("alpha",), revision=first)

    assert moved
    assert closure.verified_source_tree is None


def test__citation_closure_cli__requires_explicit_mode_and_entrypoint(
    tmp_path: Path,
) -> None:
    common = [
        "collection-reconcile",
        str(tmp_path / "references.bib"),
        str(tmp_path / "corpus.csv"),
        str(tmp_path / "pdfs"),
        str(tmp_path / "output"),
        "--collection-id",
        "synthetic",
        "--source-revision",
        "fixture",
        "--bibliography-storage-class",
        "local",
        "--corpus-storage-class",
        "local",
        "--pdf-storage-class",
        "local",
        "--output-storage-class",
        "local",
        "--manuscript-root",
        str(tmp_path / "manuscript"),
        "--manuscript-storage-class",
        "local",
    ]
    with pytest.raises(SystemExit, match="--manuscript-mode"):
        main(common)
    with pytest.raises(SystemExit, match="--manuscript-entrypoint"):
        main([*common, "--manuscript-mode", "build-graph"])


def test__citation_closure__identity_binds_configuration_and_limits(
    tmp_path: Path,
) -> None:
    root = tmp_path / "manuscript"
    root.mkdir()
    (root / "main.tex").write_text("\\cite{alpha}\n", encoding="utf-8")
    baseline = _build(root, keys=("alpha",))
    configured = _build(
        root,
        keys=("alpha",),
        configuration=replace(
            DEFAULT_CITATION_PARSER_CONFIGURATION,
            aliases=(("fixturecite", "cite"),),
        ),
    )
    tightened_limits = replace(RECONCILIATION_IO_LIMITS, max_candidates=1)
    bounded = build_citation_closure(
        root,
        storage_class=RootStorageClass.LOCAL,
        mode=CitationScanMode.BUILD_GRAPH,
        entrypoint="main.tex",
        bibliography_keys=("alpha",),
        source_revision="asserted-fixture-revision",
        limits=tightened_limits,
    )

    assert configured.closure_id != baseline.closure_id
    assert bounded.closure_id != baseline.closure_id
    assert bounded.effective_limits == tightened_limits

    (root / "main.tex").write_text(
        "\\cite{alpha}\\cite{alpha}\n", encoding="utf-8"
    )
    with pytest.raises(ReferenceIOLimitError) as raised:
        build_citation_closure(
            root,
            storage_class=RootStorageClass.LOCAL,
            mode=CitationScanMode.BUILD_GRAPH,
            entrypoint="main.tex",
            bibliography_keys=("alpha",),
            source_revision="asserted-fixture-revision",
            limits=tightened_limits,
        )
    assert raised.value.coverage_status == "incomplete"
