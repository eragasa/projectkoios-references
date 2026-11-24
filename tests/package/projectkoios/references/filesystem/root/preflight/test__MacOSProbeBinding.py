from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from projectkoios.references.adapters.filesystem.macos.file.provider.placeholder.probe import (  # noqa: E501
    MacOSFileProviderPlaceholderProbe,
)


def test__macos_probe_factory__returns_separate_immutable_bindings(
    tmp_path: Path,
) -> None:
    factory = MacOSFileProviderPlaceholderProbe(tmp_path)
    metadata = tmp_path.stat()

    first = factory.bind_authorized_root(
        tmp_path,
        device=metadata.st_dev,
        inode=metadata.st_ino,
    )
    second = factory.bind_authorized_root(
        tmp_path,
        device=metadata.st_dev,
        inode=metadata.st_ino,
    )

    assert first is not None
    assert second is not None
    assert first is not second
    with ThreadPoolExecutor(max_workers=4) as executor:
        concurrent = tuple(
            executor.map(
                lambda _index: factory.bind_authorized_root(
                    tmp_path,
                    device=metadata.st_dev,
                    inode=metadata.st_ino,
                ),
                range(16),
            )
        )
    assert all(item is not None for item in concurrent)
    assert len({id(item) for item in concurrent}) == len(concurrent)
    with pytest.raises(FrozenInstanceError):
        factory.root_path = tmp_path / "other"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        first.root_device = metadata.st_dev + 1  # type: ignore[attr-defined]
    assert not hasattr(factory, "observe")
    assert (
        factory.bind_authorized_root(
            tmp_path,
            device=metadata.st_dev,
            inode=metadata.st_ino + 1,
        )
        is None
    )
