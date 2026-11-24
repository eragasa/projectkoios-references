from __future__ import annotations

from projectkoios.references.filesystem.path.validation import (
    validate_root_alias,
)

from .error import PlaceholderPreflightError
from .evidence import RootPreflightEvidence
from .identity import validate_probe_id
from .observation import PlaceholderObservation
from .probe import UNSUPPORTED_CLOUD_PLACEHOLDER_PROBE, PlaceholderProbe
from .status import PlaceholderStatus
from .storage import RootStorageClass
from .support import PlaceholderProbeSupport


def authorize_root_preflight(
    *,
    root_alias: str,
    storage_class: RootStorageClass,
    placeholder_probe: PlaceholderProbe | None,
) -> RootPreflightEvidence:
    """Validate root capability before touching its filesystem path."""
    validate_root_alias(root_alias)
    if not isinstance(storage_class, RootStorageClass):
        raise ValueError("root storage class must be explicit")
    if storage_class is RootStorageClass.LOCAL:
        if placeholder_probe is not None:
            raise ValueError("local roots must not supply a cloud probe")
        return RootPreflightEvidence(
            root_alias=root_alias,
            storage_class=storage_class,
            probe_id="local-root-no-cloud-probe-v1",
            probe_support=None,
        )
    probe = placeholder_probe or UNSUPPORTED_CLOUD_PLACEHOLDER_PROBE
    try:
        probe_id = validate_probe_id(probe.probe_id)
        support = probe.support(root_alias=root_alias)
    except Exception as error:
        observation = PlaceholderObservation(
            root_alias=root_alias,
            relative_path=None,
            storage_class=storage_class,
            probe_id="ambiguous-cloud-placeholder-probe-v1",
            status=PlaceholderStatus.AMBIGUOUS,
        )
        raise PlaceholderPreflightError(observation) from error
    if not isinstance(support, PlaceholderProbeSupport):
        observation = PlaceholderObservation(
            root_alias=root_alias,
            relative_path=None,
            storage_class=storage_class,
            probe_id=probe_id,
            status=PlaceholderStatus.AMBIGUOUS,
        )
        raise PlaceholderPreflightError(observation)
    if support is not PlaceholderProbeSupport.SUPPORTED:
        status = (
            PlaceholderStatus.UNSUPPORTED_PLATFORM
            if support is PlaceholderProbeSupport.UNSUPPORTED_PLATFORM
            else PlaceholderStatus.AMBIGUOUS
        )
        observation = PlaceholderObservation(
            root_alias=root_alias,
            relative_path=None,
            storage_class=storage_class,
            probe_id=probe_id,
            status=status,
        )
        raise PlaceholderPreflightError(observation)
    return RootPreflightEvidence(
        root_alias=root_alias,
        storage_class=storage_class,
        probe_id=probe_id,
        probe_support=support,
    )
