from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from projectkoios.base import (
    DataObjectActionizer,
    DataObjectActionRequest,
    DataObjectActionResult,
    DataObjectModel,
)
from projectkoios.references.citation_draft import (
    CitationDraftEntry,
    CitationDraftError,
    CitationDraftParser,
    CitationDraftParseRequest,
    CitationDraftParseResult,
    CitationDraftRenderer,
    CitationDraftRenderRequest,
    CitationDraftRenderResult,
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


def _parse(content: bytes) -> CitationDraftParseResult:
    return CitationDraftParser().parse(
        request=CitationDraftParseRequest(content=content)
    )


def test__citation_draft_parser__uses_canonical_base_roles_and_identities() -> (
    None
):
    request = CitationDraftParseRequest(content=_payload())
    parser = CitationDraftParser()

    parsed = parser.parse(request=request)

    assert issubclass(CitationDraftEntry, DataObjectModel)
    assert issubclass(CitationDraftParseRequest, DataObjectActionRequest)
    assert issubclass(CitationDraftParseResult, DataObjectActionResult)
    assert issubclass(CitationDraftParser, DataObjectActionizer)
    assert parser.action(request=request) == parsed
    assert parsed.request is request
    assert parsed == _parse(_payload())
    assert parsed.result_id != request.request_id
    assert parsed.entries[0].entry_id.startswith("citation-draft-entry:sha256:")
    with pytest.raises(FrozenInstanceError):
        request.content = b"{}"  # type: ignore[misc]


def _render(
    entries: tuple[CitationDraftEntry, ...],
) -> CitationDraftRenderResult:
    return CitationDraftRenderer().render(
        request=CitationDraftRenderRequest(entries=entries)
    )


def test__renderer__uses_canonical_base_roles_and_identities() -> None:
    entries = _parse(_payload()).entries
    request = CitationDraftRenderRequest(entries=entries)
    renderer = CitationDraftRenderer()

    rendered = renderer.render(request=request)

    assert issubclass(CitationDraftRenderRequest, DataObjectActionRequest)
    assert issubclass(CitationDraftRenderResult, DataObjectActionResult)
    assert issubclass(CitationDraftRenderer, DataObjectActionizer)
    assert renderer.action(request=request) == rendered
    assert rendered.request is request
    assert rendered == _render(entries)
    assert rendered.result_id != request.request_id
    with pytest.raises(FrozenInstanceError):
        rendered.bibliography = b""  # type: ignore[misc]


def test__citation_draft__renders_deterministic_bibtex() -> None:
    entries = _parse(_payload()).entries

    assert _render(entries).bibliography.decode() == (
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


def test__citation_draft_parser__rejects_duplicate_members_and_authority() -> (
    None
):
    with pytest.raises(CitationDraftError, match="malformed JSON"):
        _parse(b'{"schema_version":1,"schema_version":1,"entries":[]}')
    entry = _entry()
    entry["authority"] = "canonical"
    with pytest.raises(CitationDraftError, match="candidate authority"):
        _parse(_payload(entry))


def test__legacy_entry_points__warn_and_forward() -> None:
    with pytest.warns(DeprecationWarning, match="CitationDraftParser"):
        entries = parse_citation_drafts(_payload())
    with pytest.warns(DeprecationWarning, match="CitationDraftRenderer"):
        bibliography = render_bibtex(entries)

    assert entries == _parse(_payload()).entries
    assert bibliography == _render(entries).bibliography


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
    assert (
        output.read_bytes()
        == _render(_parse(metadata.read_bytes()).entries).bibliography
    )
    with pytest.raises(FileExistsError):
        main(arguments)
