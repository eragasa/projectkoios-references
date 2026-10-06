from __future__ import annotations

import pytest
from projectkoios.references.citation.key.error import CitationKeyError
from projectkoios.references.citation.key.validation import validate_citekey


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
    with pytest.raises(CitationKeyError, match="citekey"):
        validate_citekey(value)
