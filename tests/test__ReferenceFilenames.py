from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from projectkoios.base import DataObjectModel
from projectkoios.references import ReferenceFilenames


def test__from_citekey__uses_key_for_note_and_pdf_basenames() -> None:
    filenames = ReferenceFilenames.from_citekey("luttingerKohn1955")

    assert isinstance(filenames, DataObjectModel)
    assert filenames.note == Path("luttingerKohn1955.md")
    assert filenames.pdf == Path("luttingerKohn1955.pdf")
    assert not hasattr(filenames, "__dict__")
    with pytest.raises(FrozenInstanceError):
        filenames.citekey = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "citekey",
    ["", "1955luttingerKohn", "../private", "key/name", "key name"],
)
def test__from_citekey__rejects_nonportable_keys(citekey: str) -> None:
    with pytest.raises(ValueError, match="citekey"):
        ReferenceFilenames.from_citekey(citekey)
