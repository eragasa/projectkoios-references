from __future__ import annotations

from pathlib import Path

from projectkoios.references.biblatex import load_bibliography


def test__biblatex_import__preserves_key_and_occurrence(
    tmp_path: Path,
) -> None:
    bibliography = tmp_path / "references.bib"
    bibliography.write_text(
        """@article{Example2020,
  author = {Doe, Jane and Smith, John},
  title = {An {Example} Article},
  year = {2020},
  doi = {https://doi.org/10.1234/EXAMPLE}
}
""",
        encoding="utf-8",
    )

    imported = load_bibliography(
        bibliography,
        source_id="project",
        source_revision="abc123",
        source_path="docs/references.bib",
    )

    assert imported.records[0].citekey == "Example2020"
    assert imported.records[0].doi == "10.1234/example"
    assert imported.occurrences[0].source_path == "docs/references.bib"
