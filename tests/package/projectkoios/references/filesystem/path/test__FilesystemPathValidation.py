from __future__ import annotations

import unicodedata

import pytest
from projectkoios.references.filesystem.path.error import FilesystemPathError
from projectkoios.references.filesystem.path.validation import (
    validate_relative_path,
)


def test__validate_relative_path__requires_normalized_portable_form() -> None:
    assert validate_relative_path("collection/example2026.pdf").as_posix() == (
        "collection/example2026.pdf"
    )
    assert validate_relative_path("café/example.pdf").as_posix() == (
        "café/example.pdf"
    )

    decomposed = unicodedata.normalize("NFD", "café/example.pdf")
    for value in (
        "../example.pdf",
        "/example.pdf",
        "collection\\example.pdf",
        "collection//example.pdf",
        "collection/./example.pdf",
        "collection/CON.pdf",
        "collection/example. ",
        decomposed,
    ):
        with pytest.raises(FilesystemPathError):
            validate_relative_path(value)
