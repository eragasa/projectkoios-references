from __future__ import annotations

import json
from pathlib import Path

import pytest
from projectkoios.references.citation_draft import (
    CitationDraftError,
    parse_citation_drafts,
    render_bibtex,
)
from projectkoios.references.cli import main


def _entry() -> dict[str, object]:
    return {
        "authority": "proposed-noncanonical",
        "proposed_citekey": "nistButcherEtAl2023AppendixC",
        "entry_type": "techreport",
        "title": "Appendix C. General Tables of Units of Measurement",
        "personal_authors": ["Tina G. Butcher", "Elizabeth J. Benham"],
        "corporate_authors": [],
        "year": "2023",
        "institution": "National Institute of Standards and Technology",
        "publisher": None,
        "report_type": "NIST Handbook",
        "number": "44",
        "edition": None,
        "version_note": None,
        "doi": "10.6028/nist.hb.44-2023",
        "url": "https://doi.org/10.6028/NIST.HB.44-2023",
        "urldate": "2026-09-21",
        "source_sha256": "a" * 64,
        "source_byte_size": 1234,
    }


def _payload(entry: dict[str, object] | None = None) -> bytes:
    return json.dumps(
        {"schema_version": 1, "entries": [entry or _entry()]},
        separators=(",", ":"),
    ).encode()


def test__citation_draft__renders_deterministic_bibtex() -> None:
    entries = parse_citation_drafts(_payload())

    assert render_bibtex(entries).decode() == (
        "@techreport{nistButcherEtAl2023AppendixC,\n"
        "  author = {Tina G. Butcher and Elizabeth J. Benham},\n"
        "  title = {{Appendix C. General Tables of Units of Measurement}},\n"
        "  institution = {National Institute of Standards and Technology},\n"
        "  type = {NIST Handbook},\n"
        "  number = {44},\n"
        "  year = {2023},\n"
        "  doi = {10.6028/nist.hb.44-2023},\n"
        "  url = {https://doi.org/10.6028/NIST.HB.44-2023},\n"
        "  urldate = {2026-09-21}\n"
        "}\n"
    )


def test__citation_draft__rejects_duplicate_members_and_authority() -> None:
    with pytest.raises(CitationDraftError, match="malformed JSON"):
        parse_citation_drafts(
            b'{"schema_version":1,"schema_version":1,"entries":[]}'
        )
    entry = _entry()
    entry["authority"] = "canonical"
    with pytest.raises(CitationDraftError, match="candidate authority"):
        parse_citation_drafts(_payload(entry))


def test__bib_render_cli__publishes_without_overwrite(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    metadata = tmp_path / "draft.json"
    metadata.write_bytes(_payload())
    output = tmp_path / "draft.bib"
    arguments = [
        "bib-render",
        str(metadata),
        str(output),
        "--metadata-storage-class",
        "local",
        "--output-storage-class",
        "local",
    ]

    assert main(arguments) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["authority"] == "proposed-noncanonical"
    assert output.read_bytes() == render_bibtex(
        parse_citation_drafts(metadata.read_bytes())
    )
    with pytest.raises(FileExistsError):
        main(arguments)
