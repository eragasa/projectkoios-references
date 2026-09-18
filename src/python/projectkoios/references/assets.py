from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from projectkoios.references.models import ReferenceRecord
from projectkoios.references.naming import ReferenceFilenames


def _normalized_words(value: str) -> tuple[str, ...]:
    plain = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    )
    return tuple(re.findall(r"[a-z0-9]+", plain.lower()))


@dataclass(frozen=True)
class SearchRoot:
    alias: str
    path: Path

    def __post_init__(self) -> None:
        if not self.alias or "/" in self.alias or "\\" in self.alias:
            raise ValueError("search-root alias must be one path-safe segment")


@dataclass(frozen=True)
class AssetCandidate:
    citekey: str
    root_alias: str
    relative_path: str
    score: float
    evidence: tuple[str, ...]
    recommendation: str
    sha256: str
    byte_size: int


@dataclass(frozen=True)
class AssetDiscoveryPlan:
    schema_version: int
    candidates: tuple[AssetCandidate, ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> AssetDiscoveryPlan:
        data = json.loads(text)
        if data.get("schema_version") != 1:
            raise ValueError("unsupported asset-plan schema version")
        return cls(
            schema_version=1,
            candidates=tuple(
                AssetCandidate(
                    citekey=item["citekey"],
                    root_alias=item["root_alias"],
                    relative_path=item["relative_path"],
                    score=float(item["score"]),
                    evidence=tuple(item["evidence"]),
                    recommendation=item["recommendation"],
                    sha256=item["sha256"],
                    byte_size=int(item["byte_size"]),
                )
                for item in data["candidates"]
            ),
        )


class AssetDiscoveryPlanner:
    """Produce conservative PDF candidates without mutating any source."""

    def scan(
        self,
        records: tuple[ReferenceRecord, ...],
        roots: tuple[SearchRoot, ...],
    ) -> AssetDiscoveryPlan:
        candidates: list[AssetCandidate] = []
        for root in roots:
            for path in sorted(root.path.rglob("*.pdf")):
                if not path.is_file():
                    continue
                for record in records:
                    score, evidence = self._score(record, path)
                    if score < 0.5:
                        continue
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    relative = path.relative_to(root.path).as_posix()
                    candidates.append(
                        AssetCandidate(
                            citekey=record.citekey,
                            root_alias=root.alias,
                            relative_path=relative,
                            score=score,
                            evidence=evidence,
                            recommendation=(
                                "strong-candidate"
                                if score >= 0.9
                                else "manual-review"
                            ),
                            sha256=digest,
                            byte_size=path.stat().st_size,
                        )
                    )
        ordered = tuple(
            sorted(
                candidates,
                key=lambda item: (
                    item.citekey,
                    -item.score,
                    item.root_alias,
                    item.relative_path,
                ),
            )
        )
        return AssetDiscoveryPlan(schema_version=1, candidates=ordered)

    @staticmethod
    def _score(
        record: ReferenceRecord,
        path: Path,
    ) -> tuple[float, tuple[str, ...]]:
        stem_words = _normalized_words(path.stem)
        stem_joined = "".join(stem_words)
        key_joined = "".join(_normalized_words(record.citekey))
        evidence: list[str] = []
        score = 0.0
        if stem_joined == key_joined:
            score = 1.0
            evidence.append("exact-citekey-filename")
        elif key_joined and key_joined in stem_joined:
            score = 0.9
            evidence.append("citekey-contained-in-filename")

        title_words = _normalized_words(record.title or "")
        significant = tuple(word for word in title_words if len(word) >= 4)
        if significant:
            overlap = len(set(significant) & set(stem_words)) / len(
                set(significant)
            )
            if overlap >= 0.8 and score < 0.95:
                score = 0.95
                evidence.append("strong-title-filename-match")
            elif overlap >= 0.5 and score < 0.6:
                score = 0.6
                evidence.append("partial-title-filename-match")

        if record.year and record.year in stem_words:
            evidence.append("year-in-filename")
            score = min(1.0, score + 0.05)
        return score, tuple(evidence)


def materialize_asset(
    candidate: AssetCandidate,
    *,
    roots: tuple[SearchRoot, ...],
    destination_directory: Path,
) -> Path:
    """Copy one explicitly selected strong candidate and verify its hash."""
    if candidate.recommendation != "strong-candidate":
        raise ValueError("only strong candidates can be materialized")
    root_paths = {root.alias: root.path.resolve() for root in roots}
    if candidate.root_alias not in root_paths:
        raise ValueError("candidate search-root alias was not supplied")
    relative = PurePosixPath(candidate.relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("candidate path must be safe and relative")
    source = (root_paths[candidate.root_alias] / Path(relative)).resolve()
    if not source.is_relative_to(root_paths[candidate.root_alias]):
        raise ValueError("candidate escapes its search root")
    content = source.read_bytes()
    if hashlib.sha256(content).hexdigest() != candidate.sha256:
        raise ValueError("candidate source hash changed after planning")
    if len(content) != candidate.byte_size:
        raise ValueError("candidate source size changed after planning")

    destination_directory.mkdir(parents=True, exist_ok=True)
    destination = (
        destination_directory
        / ReferenceFilenames.from_citekey(candidate.citekey).pdf
    )
    if destination.exists():
        if (
            hashlib.sha256(destination.read_bytes()).hexdigest()
            == candidate.sha256
        ):
            return destination
        raise FileExistsError(
            f"destination exists with different bytes: {destination}"
        )
    temporary = destination.with_suffix(".pdf.tmp")
    try:
        temporary.write_bytes(content)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
