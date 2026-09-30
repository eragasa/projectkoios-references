from __future__ import annotations

import ast
import re
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
ARCHITECTURE = REPOSITORY / "docs" / "architecture"
MODULE_NAME = "citation_identity"
MODULE_DIRECTORY = ARCHITECTURE / "projectkoios" / "references" / MODULE_NAME
PUBLIC_CLASSES = {
    "CitationIdentityProjectionItem",
    "CitationIdentityProjectionRequest",
    "CitationIdentityProjectionResult",
    "CitationIdentityProjectionStatus",
    "CitationIdentityProjector",
}
PACKAGE_DIRECTORIES = {
    ARCHITECTURE / "projectkoios",
    ARCHITECTURE / "projectkoios" / "references",
}
NODE_DOCUMENTS = {"implementation.md", "index.md", "schematic.md"}
EXPECTED_REMAINING_MODULES = {
    "projectkoios.references.acquisition",
    "projectkoios.references.assets",
    "projectkoios.references.biblatex",
    "projectkoios.references.catalog",
    "projectkoios.references.citation_closure",
    "projectkoios.references.citation_draft",
    "projectkoios.references.collection_reconciliation",
    "projectkoios.references.coverage",
    "projectkoios.references.enrichment",
    "projectkoios.references.graph",
    "projectkoios.references.identity",
    "projectkoios.references.ingestion_evidence",
    "projectkoios.references.io_limits",
    "projectkoios.references.models",
    "projectkoios.references.naming",
    "projectkoios.references.path_safety",
    "projectkoios.references.pdf_corpus",
    "projectkoios.references.provided_intake",
    "projectkoios.references.reconciliation_package",
    "projectkoios.references.review",
    "projectkoios.references.state_projection",
    "projectkoios.references.validation",
    "scripts.koios_ref",
    "scripts.verify_taxonomy_milestone",
}
_LINK = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
_MERMAID = re.compile(
    r"```mermaid\s+(?:flowchart|graph|classDiagram|sequenceDiagram|stateDiagram)",
    re.MULTILINE,
)


def _public_classes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
    }


def _expected_documents() -> set[Path]:
    expected = {ARCHITECTURE / "index.md"}
    for directory in (*PACKAGE_DIRECTORIES, MODULE_DIRECTORY):
        expected.update(directory / name for name in NODE_DOCUMENTS)
    expected.update(
        MODULE_DIRECTORY / class_name / "index.md"
        for class_name in PUBLIC_CLASSES
    )
    return expected


def _markdown_links(path: Path) -> tuple[Path, ...]:
    resolved: list[Path] = []
    for target in _LINK.findall(path.read_text(encoding="utf-8")):
        if target.startswith(("https://", "http://", "mailto:", "#")):
            continue
        location = target.split("#", 1)[0]
        if location:
            resolved.append((path.parent / location).resolve())
    return tuple(resolved)


def _source_modules() -> set[str]:
    references = REPOSITORY / "src" / "python" / "projectkoios" / "references"
    modules = {
        f"projectkoios.references.{path.stem}"
        for path in references.glob("*.py")
        if path.name != "__init__.py"
    }
    modules.update(
        f"scripts.{path.stem}"
        for path in (REPOSITORY / "scripts").glob("*.py")
        if path.name != "__init__.py"
    )
    return modules


def _source_public_class_count() -> int:
    paths = tuple(
        path
        for path in (
            REPOSITORY / "src" / "python" / "projectkoios" / "references"
        ).glob("*.py")
        if path.name != "__init__.py"
    ) + tuple(
        path
        for path in (REPOSITORY / "scripts").glob("*.py")
        if path.name != "__init__.py"
    )
    return sum(len(_public_classes(path)) for path in paths)


def test__architecture_docs__cover_exact_touched_vertical_slice() -> None:
    source = (
        REPOSITORY
        / "src"
        / "python"
        / "projectkoios"
        / "references"
        / f"{MODULE_NAME}.py"
    )
    assert _public_classes(source) == PUBLIC_CLASSES

    actual = set(ARCHITECTURE.rglob("*.md"))
    expected = _expected_documents()
    assert actual == expected
    assert len(actual) == 15

    mermaid_documents = {
        directory / name
        for directory in (*PACKAGE_DIRECTORIES, MODULE_DIRECTORY)
        for name in ("schematic.md", "implementation.md")
    }
    assert len(mermaid_documents) == 6
    for path in mermaid_documents:
        assert _MERMAID.search(path.read_text(encoding="utf-8")), path


def test__architecture_docs__report_remaining_modules_without_completion() -> (
    None
):
    all_modules = _source_modules()
    migrated = {f"projectkoios.references.{MODULE_NAME}"}
    assert all_modules - migrated == EXPECTED_REMAINING_MODULES

    navigator = (ARCHITECTURE / "index.md").read_text(encoding="utf-8")
    assert "does not claim repository-wide documentation coverage" in navigator
    assert "15 pages; 269 remain unmigrated" in navigator
    for module in EXPECTED_REMAINING_MODULES:
        assert f"`{module}`" in navigator

    package_count = 3
    expected_total = (
        1
        + package_count * 3
        + len(all_modules) * 3
        + _source_public_class_count()
    )
    assert expected_total == 284


def test__architecture_docs__have_no_orphans_or_broken_local_links() -> None:
    expected = _expected_documents()
    links = {path: _markdown_links(path) for path in expected}
    for path, targets in links.items():
        for target in targets:
            assert target.exists(), f"{path}: missing link target {target}"

    reachable = {ARCHITECTURE / "index.md"}
    pending = list(reachable)
    while pending:
        current = pending.pop()
        for target in links[current]:
            if target in expected and target not in reachable:
                reachable.add(target)
                pending.append(target)
    assert reachable == expected
