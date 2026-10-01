from __future__ import annotations

import ast
import re
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
ARCHITECTURE = REPOSITORY / "docs" / "architecture"
MIGRATED_MODULES = {
    "bibliography": {
        "CitationBibliographyMembershipStatus",
        "CitationBibliographyObservationBinding",
    },
    "citations": {
        "CitationContentIdentity",
        "CitationKeyResolutionStatus",
        "CitationSourceLocator",
        "CitationTargetBibliographyEntry",
        "CitationTargetGroup",
        "CitationTargetOccurrence",
        "CitationTargetSnapshot",
        "CitationTargetSourceGap",
    },
    "citation_document": {
        "CitationDocumentAvailabilityStatus",
        "CitationDocumentProjection",
        "CitationDocumentProjectionItem",
        "CitationDocumentProjectionRequest",
        "CitationDocumentProjectionResult",
        "CitationDocumentProjector",
        "CitationSourceDocumentDescriptor",
        "CitationSourceDocumentLink",
        "CitationSourceDocumentLinkRequest",
        "CitationSourceDocumentLinkResult",
        "CitationSourceDocumentLinker",
        "CitationSourceDocumentObservation",
    },
    "citation_identity": {
        "CitationIdentityProjectionItem",
        "CitationIdentityProjectionRequest",
        "CitationIdentityProjectionResult",
        "CitationIdentityProjectionStatus",
        "CitationIdentityProjector",
    },
}
MODULE_DIRECTORIES = {
    name: ARCHITECTURE / "projectkoios" / "references" / name
    for name in MIGRATED_MODULES
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
    sources = tuple(path.glob("*.py")) if path.is_dir() else (path,)
    result: set[str] = set()
    for source in sources:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        result.update(
            node.name
            for node in tree.body
            if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
        )
    return result


def _expected_documents() -> set[Path]:
    expected = {ARCHITECTURE / "index.md"}
    for directory in (*PACKAGE_DIRECTORIES, *MODULE_DIRECTORIES.values()):
        expected.update(directory / name for name in NODE_DOCUMENTS)
    for module_name, public_classes in MIGRATED_MODULES.items():
        expected.update(
            MODULE_DIRECTORIES[module_name] / class_name / "index.md"
            for class_name in public_classes
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
        f"projectkoios.references.{path.name}"
        for path in references.iterdir()
        if path.is_dir()
        and not path.name.startswith("_")
        and (path / "__init__.py").is_file()
    )
    modules.update(
        f"scripts.{path.stem}"
        for path in (REPOSITORY / "scripts").glob("*.py")
        if path.name != "__init__.py"
    )
    return modules


def _source_public_class_count() -> int:
    references = REPOSITORY / "src" / "python" / "projectkoios" / "references"
    paths = (
        tuple(
            path
            for path in references.glob("*.py")
            if path.name != "__init__.py"
        )
        + tuple(
            path
            for package in references.iterdir()
            if package.is_dir() and (package / "__init__.py").is_file()
            for path in package.glob("*.py")
        )
        + tuple(
            path
            for path in (REPOSITORY / "scripts").glob("*.py")
            if path.name != "__init__.py"
        )
    )
    return sum(len(_public_classes(path)) for path in paths)


def test__architecture_docs__cover_exact_touched_vertical_slices() -> None:
    source_root = REPOSITORY / "src" / "python" / "projectkoios" / "references"
    assert not (source_root / "citation_document.py").exists()
    assert (source_root / "citation_document" / "__init__.py").is_file()
    assert not (source_root / "citation_document" / "target.py").exists()
    assert (source_root / "citations" / "base.py").is_file()
    assert (source_root / "bibliography" / "base.py").is_file()
    for module_name, public_classes in MIGRATED_MODULES.items():
        module_file = source_root / f"{module_name}.py"
        module_path = (
            module_file if module_file.is_file() else source_root / module_name
        )
        assert _public_classes(module_path) == public_classes

    actual = set(ARCHITECTURE.rglob("*.md"))
    expected = _expected_documents()
    assert actual == expected
    assert len(actual) == 46

    mermaid_documents = {
        directory / name
        for directory in (
            *PACKAGE_DIRECTORIES,
            *MODULE_DIRECTORIES.values(),
        )
        for name in ("schematic.md", "implementation.md")
    }
    assert len(mermaid_documents) == 12
    for path in mermaid_documents:
        assert _MERMAID.search(path.read_text(encoding="utf-8")), path


def test__architecture_docs__report_remaining_modules_without_completion() -> (
    None
):
    all_modules = _source_modules()
    migrated = {f"projectkoios.references.{name}" for name in MIGRATED_MODULES}
    assert all_modules - migrated == EXPECTED_REMAINING_MODULES

    navigator = (ARCHITECTURE / "index.md").read_text(encoding="utf-8")
    assert "does not claim repository-wide documentation coverage" in navigator
    assert "46 pages; 269 remain unmigrated" in navigator
    for module in EXPECTED_REMAINING_MODULES:
        assert f"`{module}`" in navigator

    package_count = 3
    expected_total = (
        1
        + package_count * 3
        + len(all_modules) * 3
        + _source_public_class_count()
    )
    assert expected_total == 315


def test__citation_package_dependencies_are_one_way() -> None:
    source_root = REPOSITORY / "src" / "python" / "projectkoios" / "references"
    forbidden_document = "projectkoios.references.citation_document"
    forbidden_bibliography = "projectkoios.references.bibliography"
    for package_name in ("citations", "bibliography"):
        for source in (source_root / package_name).glob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            imported_modules = {
                node.module
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module is not None
            }
            imported_modules.update(
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            )
            assert all(
                not name.startswith(forbidden_document)
                for name in imported_modules
            ), source
            if package_name == "citations":
                assert all(
                    not name.startswith(forbidden_bibliography)
                    for name in imported_modules
                ), source


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
