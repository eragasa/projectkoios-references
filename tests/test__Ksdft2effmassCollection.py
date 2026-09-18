import csv
import json
import re
from pathlib import Path

from projectkoios.references import (
    AmbiguityEvaluation,
    CoverageObservation,
    CoverageState,
    LegacySeedMapping,
    load_bibliography,
)

_PROJECT_ROOT = Path(__file__).parent.parent
_COLLECTION = _PROJECT_ROOT / "collections/ksdft2effmass"


def _seed_keys() -> list[str]:
    seed = (_COLLECTION / "seed.bib").read_text(encoding="utf-8")
    return re.findall(r"(?m)^\s*@\w+\s*\{\s*([^,\s]+)", seed)


def test__ksdft2effmass_collection__has_one_row_per_unique_key() -> None:
    keys = _seed_keys()
    with (_COLLECTION / "corpus.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))

    assert len(keys) == len(set(keys))
    assert {row["citekey"] for row in rows} == set(keys)


def test__ksdft2effmass_seed__maps_to_candidates_without_authority() -> None:
    imported = load_bibliography(
        _COLLECTION / "seed.bib",
        source_id="ksdft2effmass-legacy-seed",
        source_revision="asserted-legacy-revision",
    )
    mappings = tuple(
        LegacySeedMapping.from_candidate(candidate)
        for candidate in imported.candidates
    )

    assert len(mappings) == len(_seed_keys())
    assert {item.legacy_citekey for item in mappings} == set(_seed_keys())
    assert {item.canonical_authority for item in mappings} == {
        "not-established"
    }
    assert all(
        candidate.lifecycle_status == "unaccepted-candidate"
        for candidate in imported.candidates
    )


def test__ksdft2effmass_collection__uses_key_named_paths() -> None:
    with (_COLLECTION / "corpus.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))

    for row in rows:
        key = row["citekey"]
        assert Path(row["note_path"]).name == f"{key}.md"
        if row["pdf_path"]:
            assert Path(row["pdf_path"]).name == f"{key}.pdf"


def test__source_discovery__contains_privacy_reduced_paths() -> None:
    report = json.loads(
        (_COLLECTION / "source-discovery.json").read_text(encoding="utf-8")
    )

    assert report["privacy"]["absolute_paths_recorded"] is False
    for match in report["matches"]:
        assert not Path(match["source_relative_path"]).is_absolute()
        assert Path(match["vault_asset"]).name == (f"{match['citekey']}.pdf")
        assert re.fullmatch(r"[0-9a-f]{64}", match["sha256"])


def test__coverage_observation__marks_legacy_search_incomplete() -> None:
    observation = CoverageObservation.from_json(
        (_COLLECTION / "coverage-observation.json").read_text(encoding="utf-8")
    )

    assert observation.state is CoverageState.INCOMPLETE
    assert observation.ambiguity_evaluation is AmbiguityEvaluation.NOT_EVALUATED
    assert len(observation.references) == 90
    assert {item.citekey for item in observation.references} == set(
        _seed_keys()
    )
    assert sum(item.no_match for item in observation.references) == 68
