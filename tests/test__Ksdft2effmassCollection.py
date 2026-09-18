import csv
import json
import re
from pathlib import Path

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
