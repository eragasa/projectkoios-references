from pathlib import Path

import pytest
from projectkoios.references import ReferenceFilenames


def test__from_citekey__uses_key_for_note_and_pdf_basenames() -> None:
    filenames = ReferenceFilenames.from_citekey("luttingerKohn1955")

    assert filenames.note == Path("luttingerKohn1955.md")
    assert filenames.pdf == Path("luttingerKohn1955.pdf")


@pytest.mark.parametrize(
    "citekey",
    ["", "1955luttingerKohn", "../private", "key/name", "key name"],
)
def test__from_citekey__rejects_nonportable_keys(citekey: str) -> None:
    with pytest.raises(ValueError, match="citekey"):
        ReferenceFilenames.from_citekey(citekey)
