"""Typed construction of the concrete filesystem authority runtime."""

from __future__ import annotations

from dataclasses import dataclass

from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
)
from projectkoios.references.catalog import ReferenceCatalog
from projectkoios.references.courses.authority.asset_preview import (
    CanonicalAssetDecisionPreviewActionizer,
)
from projectkoios.references.courses.authority.asset_put import (
    PutCanonicalAssetDecisionActionizer,
)
from projectkoios.references.courses.authority.identity_preview import (
    ReferenceIdentityDecisionPreviewActionizer,
)
from projectkoios.references.courses.authority.identity_put import (
    PutReferenceIdentityDecisionActionizer,
)
from projectkoios.references.courses.authority.service import (
    CourseReferenceAuthorityLoadActionizer,
    ReferenceAuthorityIdempotencyLookupActionizer,
    ReferenceAuthorityReceiptActionizer,
)
from projectkoios.references.courses.transport.asset import (
    CanonicalAssetPreviewTransportActionizer,
    CanonicalAssetPutTransportActionizer,
)
from projectkoios.references.courses.transport.identity import (
    ReferenceIdentityPreviewTransportActionizer,
    ReferenceIdentityPutTransportActionizer,
)
from projectkoios.references.courses.transport.queue import (
    CourseReferenceQueueTransportActionizer,
)

from .configuration import CourseReferenceAuthorityRuntimeConfiguration
from .filesystem import (
    FilesystemCourseReferenceAuthorityEvidenceLoadActionizer,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class FilesystemCourseReferenceAuthorityRuntimeCreateRequest(
    DataObjectActionRequest
):
    """Request construction of one filesystem-backed authority runtime."""

    configuration: CourseReferenceAuthorityRuntimeConfiguration

    def __post_init__(self) -> None:
        """Validate the immutable construction request."""
        if type(self.configuration) is not (
            CourseReferenceAuthorityRuntimeConfiguration
        ):
            raise TypeError("configuration has an invalid type")


@dataclass(frozen=True, slots=True, kw_only=True)
class FilesystemCourseReferenceAuthorityRuntimeCreateResult(
    DataObjectActionResult
):
    """Expose only the five supported HTTP-safe transport capabilities."""

    queue: CourseReferenceQueueTransportActionizer
    identity_preview: ReferenceIdentityPreviewTransportActionizer
    asset_preview: CanonicalAssetPreviewTransportActionizer
    identity_put: ReferenceIdentityPutTransportActionizer
    asset_put: CanonicalAssetPutTransportActionizer

    def __post_init__(self) -> None:
        """Validate the exact immutable runtime capability set."""
        for value, expected, label in (
            (
                self.queue,
                CourseReferenceQueueTransportActionizer,
                "queue",
            ),
            (
                self.identity_preview,
                ReferenceIdentityPreviewTransportActionizer,
                "identity_preview",
            ),
            (
                self.asset_preview,
                CanonicalAssetPreviewTransportActionizer,
                "asset_preview",
            ),
            (
                self.identity_put,
                ReferenceIdentityPutTransportActionizer,
                "identity_put",
            ),
            (
                self.asset_put,
                CanonicalAssetPutTransportActionizer,
                "asset_put",
            ),
        ):
            if type(value) is not expected:
                raise TypeError(f"{label} has an invalid type")


class FilesystemCourseReferenceAuthorityRuntimeCreateActionizer(
    DataObjectActionizer[
        FilesystemCourseReferenceAuthorityRuntimeCreateRequest,
        FilesystemCourseReferenceAuthorityRuntimeCreateResult,
    ]
):
    """Construct one immutable set of five safe transport capabilities."""

    __slots__ = ()

    def action(
        self,
        *,
        request: FilesystemCourseReferenceAuthorityRuntimeCreateRequest,
    ) -> FilesystemCourseReferenceAuthorityRuntimeCreateResult:
        """Compose the configured owner capabilities without executing them."""
        if type(request) is not (
            FilesystemCourseReferenceAuthorityRuntimeCreateRequest
        ):
            raise TypeError("request has an invalid type")
        configuration = request.configuration
        catalog = ReferenceCatalog(
            configuration.catalog_path,
            storage_class=configuration.catalog_storage_class,
        )
        evidence_loader = (
            FilesystemCourseReferenceAuthorityEvidenceLoadActionizer(
                course_id=configuration.course_id,
                bibliography_sources=configuration.bibliography_sources,
                record_discrepancies=configuration.record_discrepancies,
                asset_roots=configuration.asset_roots,
                asset_linkage_path=configuration.asset_linkage_path,
                asset_linkage_storage_class=(
                    configuration.asset_linkage_storage_class
                ),
                asset_linkage_placeholder_probe=(
                    configuration.asset_linkage_placeholder_probe
                ),
            )
        )
        loader = CourseReferenceAuthorityLoadActionizer(
            catalog=catalog,
            evidence_loader=evidence_loader,
        )
        lookup = ReferenceAuthorityIdempotencyLookupActionizer(catalog=catalog)
        receipt = ReferenceAuthorityReceiptActionizer(loader=loader)
        identity_preview = ReferenceIdentityDecisionPreviewActionizer(
            loader=loader
        )
        asset_preview = CanonicalAssetDecisionPreviewActionizer(loader=loader)
        identity_put = PutReferenceIdentityDecisionActionizer(
            catalog=catalog,
            loader=loader,
            lookup=lookup,
            receipt=receipt,
        )
        asset_put = PutCanonicalAssetDecisionActionizer(
            catalog=catalog,
            loader=loader,
            lookup=lookup,
            receipt=receipt,
        )
        return FilesystemCourseReferenceAuthorityRuntimeCreateResult(
            queue=CourseReferenceQueueTransportActionizer(queue=loader),
            identity_preview=ReferenceIdentityPreviewTransportActionizer(
                preview=identity_preview
            ),
            asset_preview=CanonicalAssetPreviewTransportActionizer(
                preview=asset_preview
            ),
            identity_put=ReferenceIdentityPutTransportActionizer(
                put=identity_put
            ),
            asset_put=CanonicalAssetPutTransportActionizer(put=asset_put),
        )
