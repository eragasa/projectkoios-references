"""Architecture ownership and documentation completeness gates.

These tests bind documented nodes to source classes and reject orphaned pages.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
ARCHITECTURE = REPOSITORY / "docs" / "architecture"
MIGRATED_MODULES = {
    "asset/application": {
        "AssetApplicationError",
        "AssetApplicationOperation",
        "AssetApplicationOperationRequest",
        "AssetApplicationOperationResult",
    },
    "bibliography": {"CitationBibliographyObservationBinding"},
    "catalog": {
        "CandidateConflictError",
        "CatalogConflictError",
        "CatalogError",
        "CatalogMigrationPlan",
        "CatalogMigrationRequired",
        "CatalogSchemaError",
        "CatalogSchemaInfo",
        "ReferenceCatalog",
        "ReferenceDocument",
        "ReferenceDocumentAudience",
        "ReferenceDocumentBinding",
        "ReferenceDocumentCatalog",
        "ReferenceDocumentNotFound",
        "ReferenceDocumentReadError",
        "ReferenceDocumentReader",
        "ReferenceDocumentReadRequest",
        "ReferenceDocumentReadResult",
        "ReferenceDocumentRegistry",
    },
    "collections/reconciliation": {
        "CitationStatus",
        "CollectionManifest",
        "CollectionReconciliationError",
        "CollectionReconciliationOperation",
        "CollectionReconciliationOperationRequest",
        "CollectionReconciliationOperationResult",
        "CollectionReconciliationRequest",
        "CollectionReconciliationResult",
        "CollectionReconciler",
        "CollectionReference",
        "CollectionRowEvidence",
        "CollectionRowsLoadRequest",
        "CollectionRowsLoadResult",
        "CollectionRowsLoader",
        "EvidenceMapping",
        "ExtraPdf",
        "IncompleteReconciliationPublicationError",
        "ManagedPdf",
        "ManagedPdfScan",
        "ManagedPdfScanRequest",
        "ManagedPdfScanResult",
        "ManagedPdfScanner",
        "PdfExpectation",
        "PdfStatus",
        "ProcessingEvidence",
        "PublicationResult",
        "ReconciliationOutputs",
        "ReconciliationPackageParseRequest",
        "ReconciliationPackageParseResult",
        "ReconciliationPackageParser",
        "ReconciliationPackageVerificationRequest",
        "ReconciliationPackageVerificationResult",
        "ReconciliationPackageVerifier",
        "ReconciliationPublicationRequest",
        "ReconciliationPublicationResult",
        "ReconciliationPublisher",
        "ReconciliationReplayRequest",
        "ReconciliationReplayResult",
        "ReconciliationReplayer",
    },
    "citations": {
        "CitationContentIdentity",
        "CitationSourceLocator",
        "CitationTargetBibliographyEntry",
        "CitationTargetGroup",
        "CitationTargetOccurrence",
        "CitationTargetSnapshot",
        "CitationTargetSourceGap",
    },
    "citation/identity": {
        "CitationIdentityProjectionItem",
        "CitationIdentityProjectionRequest",
        "CitationIdentityProjectionResult",
        "CitationIdentityProjectionStatus",
        "CitationIdentityProjector",
    },
    "state_projection_replay": {
        "ReferenceStateReplayer",
        "ReferenceStateReplayRequest",
        "ReferenceStateReplayResult",
    },
    "document/reference": {
        "AbstractDocumentReferenceDataObject",
        "AbstractRebuildReplayDataObject",
        "AbstractSameStoreReplayDataObject",
        "BibliographyMetadataError",
        "BibliographyMetadataReader",
        "BindPdfToReference",
        "BindPdfToReferenceRequest",
        "BindPdfToReferenceResult",
        "BindVerifiedLocalEvidence",
        "BindVerifiedLocalEvidenceRequest",
        "BindingDisposition",
        "DocumentContentConflict",
        "DocumentReferenceError",
        "DocumentReferenceStoreError",
        "InvalidPdfUpload",
        "ListMissingPdfReferences",
        "ListMissingPdfReferencesRequest",
        "ListMissingPdfReferencesResult",
        "MissingPdfReference",
        "MissingPdfReferencesRepository",
        "PdfObjectReceiver",
        "PdfReceiptDisposition",
        "PdfReceiptRepository",
        "PdfRequirement",
        "PdfUploadTooLarge",
        "ProvideReferencePdf",
        "ProvideReferencePdfRequest",
        "ProvideReferencePdfResult",
        "ReceiptRecordEffect",
        "ReceivePdf",
        "ReceivePdfRequest",
        "ReceivePdfResult",
        "ReferenceCollection",
        "ReferenceCollectionMembership",
        "ReferenceCollectionRepository",
        "ReferenceDisplayMetadata",
        "ReferenceDocumentBinding",
        "ReferenceDocumentBindingConflict",
        "ReferenceDocumentBindingRepository",
        "ReferenceDocumentBindingSelection",
        "ReferenceDocumentLinkageBasis",
        "ReferencePdfProvisionStatus",
        "ReferenceRecord",
        "ReferenceRecordRepository",
        "StoredPdfObject",
        "UnknownCollection",
        "UnknownDocument",
        "UnknownReference",
    },
    "filesystem": {
        "AddressedFilePublication",
        "AnonymousFilePublisher",
        "AuthorizedRoot",
        "AuthorizedRootIdentity",
        "CloudPlaceholderProbe",
        "CloudRootMutationError",
        "DirectoryPublisher",
        "FileObservation",
        "FilesystemBoundaryError",
        "FilesystemDescriptorError",
        "FilesystemInventory",
        "FilesystemInventoryIssue",
        "FilesystemIssueKind",
        "FilesystemLimitError",
        "FilesystemObservationError",
        "FilesystemOperationError",
        "FilesystemPathError",
        "FilesystemPublicationError",
        "FilesystemScanningError",
        "InventoryScanner",
        "PlaceholderObservation",
        "PlaceholderPreflightError",
        "PlaceholderProbe",
        "PlaceholderProbeSupport",
        "PlaceholderStatus",
        "PublishedFileVerifier",
        "RootBoundPlaceholderProbeFactory",
        "RootDescriptor",
        "RootObservation",
        "RootPreflightEvidence",
        "RootPublication",
        "RootScanning",
        "RootStorageClass",
        "StrictFileScanner",
        "UnsupportedCloudPlaceholderProbe",
        "VerifiedFileCopier",
    },
    "citation/key": {"CitationKeyError"},
    "ingestion/evidence": {
        "IngestionEvidenceError",
        "IngestionEvidenceLimitError",
        "IngestionEvidenceParseError",
        "IngestionEvidenceVerificationError",
        "ReferenceEvidenceArtifact",
        "ReferenceEvidenceAudit",
        "ReferenceEvidenceExtraction",
        "ReferenceEvidenceInput",
        "ReferenceEvidenceLayerCount",
        "ReferenceEvidenceRecord",
        "ReferenceEvidenceSource",
        "ReferenceEvidenceTranscript",
    },
    "adapters/filesystem/linux": set(),
    "adapters/filesystem/macos": {
        "MacOSFileProviderPlaceholderProbe",
    },
}
MIGRATED_FILE_MODULES = {
    "adapters/bibliography/pybtex_metadata_reader": {
        "PybtexBibliographyMetadataReader",
    },
    "adapters/filesystem/sha256_pdf_object_store": {
        "Sha256PdfObjectStore",
    },
    "adapters/sql/sqlite/document_reference_schema": {
        "DocumentReferenceSchema",
    },
    "adapters/sql/sqlite/document_reference_store": {
        "SqliteDocumentReferenceStore",
    },
}
MODULE_DIRECTORIES = {
    name: ARCHITECTURE / "projectkoios" / "references" / name
    for name in MIGRATED_MODULES
}
FILE_MODULE_DIRECTORIES = {
    name: ARCHITECTURE / "projectkoios" / "references" / name
    for name in MIGRATED_FILE_MODULES
}
PACKAGE_DIRECTORIES = {
    ARCHITECTURE / "projectkoios",
    ARCHITECTURE / "projectkoios" / "references",
}
NODE_DOCUMENTS = {"implementation.md", "index.md", "schematic.md"}
# Courses adopts the stronger four-view convention independently of older
# three-page migrated slices, so its expected tree is checked explicitly.
COURSES_ARCHITECTURE = ARCHITECTURE / "projectkoios" / "references" / "courses"
EXPECTED_REMAINING_MODULES = {
    "projectkoios.references.acquisition",
    "projectkoios.references.assets",
    "projectkoios.references.biblatex",
    "projectkoios.references.candidate_bibliography",
    "projectkoios.references.citation",
    "projectkoios.references.coverage",
    "projectkoios.references.enrichment",
    "projectkoios.references.graph",
    "projectkoios.references.identity",
    "projectkoios.references.io_limits",
    "projectkoios.references.models",
    "projectkoios.references.naming",
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


def _contains_python_source(path: Path) -> bool:
    """Return whether a path contains tracked-shape Python source.

    Ignored bytecode and empty directories left by branch switches are not
    implementation modules.
    """
    if path.is_file():
        return path.suffix == ".py"
    if not path.is_dir():
        return False
    return any(candidate.is_file() for candidate in path.rglob("*.py"))


def _public_classes(path: Path) -> set[str]:
    """Evaluate deterministic architecture coverage.

    Parameters
    ----------
    path
        Typed input constrained by the helper contract.

    Returns
    -------
    object
        Deterministic architecture evidence described by the annotation.
    """
    sources = tuple(path.rglob("*.py")) if path.is_dir() else (path,)
    result: set[str] = set()
    for source in sources:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        result.update(
            node.name
            for node in tree.body
            if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
        )
    return result


# Build exact expectations rather than accepting arbitrary Markdown additions;
# this makes missing, stale, and orphaned architecture pages review-visible.
def _expected_documents() -> set[Path]:
    """Evaluate deterministic architecture coverage.

    Returns
    -------
    object
        Deterministic architecture evidence described by the annotation.
    """
    expected = {ARCHITECTURE / "index.md"}
    module_directories = {
        **MODULE_DIRECTORIES,
        **FILE_MODULE_DIRECTORIES,
    }
    for directory in (*PACKAGE_DIRECTORIES, *module_directories.values()):
        expected.update(directory / name for name in NODE_DOCUMENTS)
    public_classes_by_module = {
        **MIGRATED_MODULES,
        **MIGRATED_FILE_MODULES,
    }
    for module_name, public_classes in public_classes_by_module.items():
        expected.update(
            module_directories[module_name] / class_name / "index.md"
            for class_name in public_classes
        )
    expected.update(COURSES_ARCHITECTURE.rglob("*.md"))
    return expected


def _markdown_links(path: Path) -> tuple[Path, ...]:
    """Evaluate deterministic architecture coverage.

    Parameters
    ----------
    path
        Typed input constrained by the helper contract.

    Returns
    -------
    object
        Deterministic architecture evidence described by the annotation.
    """
    resolved: list[Path] = []
    for target in _LINK.findall(path.read_text(encoding="utf-8")):
        if target.startswith(("https://", "http://", "mailto:", "#")):
            continue
        location = target.split("#", 1)[0]
        if location:
            resolved.append((path.parent / location).resolve())
    return tuple(resolved)


def _source_modules() -> set[str]:
    """Evaluate deterministic architecture coverage.

    Returns
    -------
    object
        Deterministic architecture evidence described by the annotation.
    """
    references = REPOSITORY / "src" / "python" / "projectkoios" / "references"
    modules = {
        f"projectkoios.references.{path.stem}"
        for path in references.glob("*.py")
        if path.name != "__init__.py"
    }
    modules.update(
        "projectkoios.references."
        + ".".join(path.relative_to(references).parts)
        for path in references.rglob("*")
        if path.is_dir()
        and not path.name.startswith("_")
        and (path / "__init__.py").is_file()
        and any(child.name != "__init__.py" for child in path.glob("*.py"))
    )
    modules.update(
        f"scripts.{path.stem}"
        for path in (REPOSITORY / "scripts").glob("*.py")
        if path.name != "__init__.py"
    )
    return modules


def test__source_shape__ignores_cache_only_directories(tmp_path: Path) -> None:
    """Treat ignored bytecode as workspace residue, not source structure."""
    stale = tmp_path / "removed_package" / "__pycache__"
    stale.mkdir(parents=True)
    (stale / "module.cpython-314.pyc").write_bytes(b"ignored")

    assert not _contains_python_source(stale.parent)

    (stale.parent / "module.py").write_text("value = 1\n", encoding="utf-8")
    assert _contains_python_source(stale.parent)


def test__architecture_docs__cover_exact_touched_vertical_slices() -> None:
    """Evaluate deterministic architecture coverage.

    Returns
    -------
    None
        The architecture assertion completes without an artifact.
    """
    source_root = REPOSITORY / "src" / "python" / "projectkoios" / "references"
    assert not _contains_python_source(source_root / "asset_application.py")
    assert not _contains_python_source(source_root / "asset_application")
    asset = source_root / "asset"
    asset_application = asset / "application"
    assert asset_application.is_dir()
    for initializer in (
        asset / "__init__.py",
        asset_application / "__init__.py",
    ):
        tree = ast.parse(initializer.read_text(encoding="utf-8"))
        assert all(
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            for node in tree.body
        ), initializer
    assert {
        path.name
        for path in asset_application.glob("*.py")
        if path.name != "__init__.py"
    } == {"action.py", "error.py", "request.py", "result.py"}
    for source in asset_application.glob("*.py"):
        if source.name == "__init__.py":
            continue
        assert len(_public_classes(source)) == 1, source
    assert not _contains_python_source(source_root / "catalog.py")
    assert not _contains_python_source(source_root / "document_reference.py")
    assert not _contains_python_source(source_root / "document_reference")
    document = source_root / "document"
    document_reference = document / "reference"
    assert document_reference.is_dir()
    for obsolete in (
        "bibliography/metadata/errors.py",
        "bindings/errors.py",
        "bindings/verified_local",
        "collections/pdf_requirement.py",
        "documents/stored_pdf.py",
        "replay/same_store",
        "replay/same",
    ):
        assert not _contains_python_source(document_reference / obsolete)
    for initializer in (
        document / "__init__.py",
        *document_reference.rglob("__init__.py"),
    ):
        tree = ast.parse(initializer.read_text(encoding="utf-8"))
        assert all(
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            for node in tree.body
        ), initializer
    for source in document_reference.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        assert not any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for node in tree.body
        ), source
        if source.name in {"__init__.py", "error.py", "errors.py"}:
            continue
        assert len(_public_classes(source)) <= 1, source
    assert (
        REPOSITORY / "tests/package/projectkoios/references/document/reference/"
        "test__DocumentReferenceOperations.py"
    ).is_file()
    assert (source_root / "catalog" / "__init__.py").is_file()
    assert not _contains_python_source(
        source_root / "collection_reconciliation.py"
    )
    assert not _contains_python_source(
        source_root / "collection_reconciliation"
    )
    assert (
        source_root / "collections" / "reconciliation" / "__init__.py"
    ).is_file()
    assert not _contains_python_source(source_root / "citation_document.py")
    assert not _contains_python_source(source_root / "citation_document")
    citation = source_root / "citation"
    assert not _contains_python_source(citation / "document")
    for flat_name in (
        "citation_closure.py",
        "citation_draft.py",
        "citation_identity.py",
    ):
        assert not (source_root / flat_name).exists()
    for owner_name in ("closure.py", "draft.py", "identity.py"):
        assert (citation / owner_name).is_file()
    tree = ast.parse((citation / "__init__.py").read_text(encoding="utf-8"))
    assert all(
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        for node in tree.body
    )
    assert (source_root / "citations" / "base.py").is_file()
    assert (source_root / "bibliography" / "base.py").is_file()
    assert not _contains_python_source(source_root / "path_safety")
    assert not _contains_python_source(source_root / "ingestion_evidence.py")
    for hierarchy in (
        source_root / "citation" / "key",
        source_root / "filesystem",
        source_root / "adapters" / "filesystem" / "linux",
        source_root / "adapters" / "filesystem" / "macos",
        source_root / "ingestion" / "evidence",
    ):
        for initializer in hierarchy.rglob("__init__.py"):
            tree = ast.parse(initializer.read_text(encoding="utf-8"))
            assert all(
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                for node in tree.body
            ), initializer
    public_classes_by_module = {
        **MIGRATED_MODULES,
        **MIGRATED_FILE_MODULES,
    }
    for module_name, public_classes in public_classes_by_module.items():
        module_file = source_root / f"{module_name}.py"
        module_path = (
            module_file
            if module_file.is_file()
            else source_root.joinpath(*module_name.split("/"))
        )
        assert _public_classes(module_path) == public_classes

    actual = set(ARCHITECTURE.rglob("*.md"))
    expected = _expected_documents()
    assert actual == expected

    mermaid_documents = {
        directory / name
        for directory in (
            *PACKAGE_DIRECTORIES,
            *MODULE_DIRECTORIES.values(),
            *FILE_MODULE_DIRECTORIES.values(),
        )
        for name in ("schematic.md", "implementation.md")
    }
    for path in mermaid_documents:
        assert _MERMAID.search(path.read_text(encoding="utf-8")), path


def test__architecture_docs__report_remaining_modules_without_completion() -> (
    None
):
    """Evaluate deterministic architecture coverage.

    Returns
    -------
    None
        The architecture assertion completes without an artifact.
    """
    all_modules = _source_modules()
    migrated = {
        "projectkoios.references." + name.replace("/", ".")
        for name in MIGRATED_MODULES
    }
    migrated.add("projectkoios.references.courses")
    remaining = {
        module
        for module in all_modules
        if not any(
            module == root or module.startswith(f"{root}.") for root in migrated
        )
    }
    assert remaining == EXPECTED_REMAINING_MODULES

    navigator = (ARCHITECTURE / "index.md").read_text(encoding="utf-8")
    assert "does not claim repository-wide documentation coverage" in navigator
    for module in EXPECTED_REMAINING_MODULES:
        assert f"`{module}`" in navigator


# Every Courses class is a public contract with a dedicated test filename and
# four-view architecture node. The mypy plugin remains the authoritative gate.
def test__courses_architecture_and_tests_mirror_every_public_class() -> None:
    """Evaluate deterministic architecture coverage.

    Returns
    -------
    None
        The architecture assertion completes without an artifact.
    """
    courses_source = (
        REPOSITORY
        / "src"
        / "python"
        / "projectkoios"
        / "references"
        / "courses"
    )
    courses_docs = ARCHITECTURE / "projectkoios" / "references" / "courses"
    courses_tests = (
        REPOSITORY
        / "tests"
        / "package"
        / "projectkoios"
        / "references"
        / "courses"
    )
    required = {"index.md", "schematics.md", "numerics.md", "scientific.md"}
    assert {item.name for item in courses_docs.glob("*.md")} == required
    for package_name in ("authority", "runtime", "transport"):
        source_package = courses_source / package_name
        package_docs = courses_docs / package_name
        assert {item.name for item in package_docs.glob("*.md")} == required
        for source in source_package.glob("*.py"):
            if source.name == "__init__.py" or source.name.startswith("_"):
                continue
            tree = ast.parse(source.read_text(encoding="utf-8"))
            classes = {
                node.name
                for node in tree.body
                if isinstance(node, ast.ClassDef)
            }
            module_docs = package_docs / source.stem
            assert {item.name for item in module_docs.glob("*.md")} == required
            for class_name in classes:
                assert tuple(
                    (courses_tests / package_name).glob(
                        f"test__{class_name}__*.py"
                    )
                )
                assert not class_name.startswith("_")
                class_docs = module_docs / class_name
                assert {
                    item.name for item in class_docs.glob("*.md")
                } == required


def test__citation_inventory_does_not_depend_on_bibliography() -> None:
    """Keep neutral citation inventory independent of References evidence."""
    source_root = REPOSITORY / "src" / "python" / "projectkoios" / "references"
    forbidden = "projectkoios.references.bibliography"
    for source in (source_root / "citations").glob("*.py"):
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
            not name.startswith(forbidden) for name in imported_modules
        ), source


# Reachability is checked from the architecture root so generated-looking
# pages cannot satisfy completeness while remaining undiscoverable.
def test__architecture_docs__have_no_orphans_or_broken_local_links() -> None:
    """Evaluate deterministic architecture coverage.

    Returns
    -------
    None
        The architecture assertion completes without an artifact.
    """
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
