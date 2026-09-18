from __future__ import annotations

import hashlib
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

    observation = imported.observations[0]
    candidate = imported.candidates[0]
    assert observation.observed_citekey == "Example2020"
    assert observation.source_path == "docs/references.bib"
    assert "title = {An {Example} Article}" in observation.verbatim_entry
    assert candidate.proposed_citekey == "Example2020"
    assert candidate.citekey_status == "proposed-noncanonical"
    assert candidate.lifecycle_status == "unaccepted-candidate"
    assert candidate.doi == "10.1234/example"
    assert candidate.source_observation_ids == (observation.observation_id,)


def test__biblatex_import__retains_exact_parenthesized_entry(
    tmp_path: Path,
) -> None:
    bibliography = tmp_path / "references.bib"
    content = (
        "@article(Paren2021,\n"
        "  title = {Use (Parentheses) Exactly},\n"
        '  year = "2021"\n'
        ")\n"
    )
    bibliography.write_bytes(content.encode("utf-8"))

    imported = load_bibliography(
        bibliography,
        source_id="project",
        source_path="docs/references.bib",
    )

    observation = imported.observations[0]
    assert observation.verbatim_entry == content.rstrip("\n")
    assert (
        observation.bibliography_sha256
        == hashlib.sha256(content.encode("utf-8")).hexdigest()
    )
