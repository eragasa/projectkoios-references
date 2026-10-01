from __future__ import annotations

import unicodedata

import pytest
from projectkoios.references import (
    PathSafetyError,
    validate_citekey,
    validate_relative_path,
)


@pytest.mark.parametrize(
    "value",
    (
        "",
        "../private",
        "/absolute",
        "key/name",
        "key\\name",
        "1955example",
        "example.",
        "CON",
        "CON.txt",
        "éxample",
        "e\N{COMBINING ACUTE ACCENT}xample",
        "a" * 201,
    ),
)
def test__validate_citekey__rejects_nonportable_values(value: str) -> None:
    with pytest.raises(PathSafetyError, match="citekey"):
        validate_citekey(value)


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
        with pytest.raises(PathSafetyError):
            validate_relative_path(value)
