from __future__ import annotations

import ast
from pathlib import Path
from typing import get_type_hints

import pytest
from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
    DataObjectModel,
)
from projectkoios.references.collections import reconciliation as package
from projectkoios.references.collections.reconciliation.classification import (
    CollectionReference,
    ExtraPdf,
)
from projectkoios.references.collections.reconciliation.evidence import (
    ProcessingEvidence,
)
from projectkoios.references.collections.reconciliation.loading import (
    CollectionRowEvidence,
    CollectionRowsLoader,
    CollectionRowsLoadRequest,
    CollectionRowsLoadResult,
    EvidenceMapping,
    ManagedPdf,
    ManagedPdfScan,
    ManagedPdfScanner,
    ManagedPdfScanRequest,
    ManagedPdfScanResult,
)
from projectkoios.references.collections.reconciliation.manifest import (
    CollectionManifest,
    ReconciliationOutputs,
)
from projectkoios.references.collections.reconciliation.publication import (
    PublicationResult,
    ReconciliationPackageParser,
    ReconciliationPackageParseRequest,
    ReconciliationPackageParseResult,
    ReconciliationPackageVerificationRequest,
    ReconciliationPackageVerificationResult,
    ReconciliationPackageVerifier,
    ReconciliationPublicationRequest,
    ReconciliationPublicationResult,
    ReconciliationPublisher,
    ReconciliationReplayer,
    ReconciliationReplayRequest,
    ReconciliationReplayResult,
)
from projectkoios.references.collections.reconciliation.reconciliation import (
    CollectionReconciler,
    CollectionReconciliationRequest,
    CollectionReconciliationResult,
)
from projectkoios.references.path_safety import RootStorageClass

_MODELS = (
    CollectionManifest,
    CollectionReference,
    CollectionRowEvidence,
    EvidenceMapping,
    ExtraPdf,
    ManagedPdf,
    ManagedPdfScan,
    ProcessingEvidence,
    PublicationResult,
    ReconciliationOutputs,
)
_REQUESTS = (
    CollectionRowsLoadRequest,
    ManagedPdfScanRequest,
    CollectionReconciliationRequest,
    ReconciliationPackageParseRequest,
    ReconciliationPackageVerificationRequest,
    ReconciliationPublicationRequest,
    ReconciliationReplayRequest,
)
_RESULTS = (
    CollectionRowsLoadResult,
    ManagedPdfScanResult,
    CollectionReconciliationResult,
    ReconciliationPackageParseResult,
    ReconciliationPackageVerificationResult,
    ReconciliationPublicationResult,
    ReconciliationReplayResult,
)
_ACTIONIZERS = (
    CollectionRowsLoader,
    ManagedPdfScanner,
    CollectionReconciler,
    ReconciliationPackageParser,
    ReconciliationPackageVerifier,
    ReconciliationPublisher,
    ReconciliationReplayer,
)
_ACTION_FAMILIES = tuple(zip(_ACTIONIZERS, _REQUESTS, strict=True))


def test__reconciliation_package__uses_classic_data_object_roles() -> None:
    assert all(issubclass(value, DataObjectModel) for value in _MODELS)
    assert all(
        issubclass(value, DataObjectActionRequest) for value in _REQUESTS
    )
    assert all(issubclass(value, DataObjectActionResult) for value in _RESULTS)
    assert all(
        issubclass(value, DataObjectActionizer) for value in _ACTIONIZERS
    )
    for actionizer in _ACTIONIZERS:
        methods = {
            name
            for name, value in vars(actionizer).items()
            if callable(value) and (not name.startswith("__"))
        }
        assert methods == {"action"}


def test__reconciliation_package__rejects_request_subtypes() -> None:
    for actionizer_type, request_type in _ACTION_FAMILIES:
        subtype = type(f"{request_type.__name__}Subtype", (request_type,), {})
        request = object.__new__(subtype)
        with pytest.raises(TypeError, match="request must be"):
            actionizer_type().action(request=request)


def test__reconciliation_actions__reject_nested_output_subtypes(
    tmp_path: Path,
) -> None:
    subtype = type("ReconciliationOutputsSubtype", (ReconciliationOutputs,), {})
    outputs = object.__new__(subtype)
    with pytest.raises(TypeError, match="exact ReconciliationOutputs"):
        ReconciliationPublisher().action(
            request=ReconciliationPublicationRequest(
                outputs=outputs,
                output_directory=tmp_path / "publication",
                output_storage_class=RootStorageClass.LOCAL,
            )
        )
    with pytest.raises(TypeError, match="exact ReconciliationOutputs"):
        ReconciliationReplayer().action(
            request=ReconciliationReplayRequest(
                outputs=outputs,
                output_directory=tmp_path / "replay",
                output_storage_class=RootStorageClass.LOCAL,
            )
        )


def test__processing_evidence__rejects_subtype_factories() -> None:
    subtype = type("ProcessingEvidenceSubtype", (ProcessingEvidence,), {})
    with pytest.raises(TypeError, match="does not support subtypes"):
        subtype.not_supplied()


def test__reconciliation_package__keeps_init_free_of_api_exports() -> None:
    source = Path(package.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    declarations = tuple(
        node
        for node in tree.body
        if not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
    )
    assert declarations == ()


def test__reconciliation_package__resolves_public_annotations() -> None:
    for value in (*_MODELS, *_REQUESTS, *_RESULTS, *_ACTIONIZERS):
        get_type_hints(value)
