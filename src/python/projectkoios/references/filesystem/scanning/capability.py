"""Composed bounded filesystem scanning capability."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import final

from projectkoios.references.filesystem.inventory.result import (
    FilesystemInventory,
)
from projectkoios.references.filesystem.root.descriptor import RootDescriptor
from projectkoios.references.filesystem.scanning.inventory.action import (
    InventoryScanner,
)
from projectkoios.references.filesystem.scanning.strict.action import (
    StrictFileScanner,
)


@final
@dataclass(frozen=True, slots=True, eq=False)
class RootScanning:
    """Compose strict listing and typed inventory traversal."""

    _descriptor: RootDescriptor
    _strict: StrictFileScanner = field(init=False, repr=False)
    _inventory: InventoryScanner = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_strict", StrictFileScanner(self._descriptor))
        object.__setattr__(
            self,
            "_inventory",
            InventoryScanner(self._descriptor),
        )

    def iter_files(
        self,
        *,
        suffix: str,
        recursive: bool,
        reject_directories: bool = False,
        max_files: int | None = None,
        max_entries: int | None = None,
        max_depth: int | None = None,
    ) -> tuple[PurePosixPath, ...]:
        return self._strict.iter_files(
            suffix=suffix,
            recursive=recursive,
            reject_directories=reject_directories,
            max_files=max_files,
            max_entries=max_entries,
            max_depth=max_depth,
        )

    def inventory_files(
        self,
        *,
        suffix: str,
        recursive: bool,
        max_files: int,
        max_entries: int,
        max_depth: int,
        case_sensitive_suffix: bool = True,
    ) -> FilesystemInventory:
        return self._inventory.inventory_files(
            suffix=suffix,
            recursive=recursive,
            max_files=max_files,
            max_entries=max_entries,
            max_depth=max_depth,
            case_sensitive_suffix=case_sensitive_suffix,
        )
