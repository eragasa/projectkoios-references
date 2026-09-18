from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from projectkoios.references.identity import ReferenceCandidate
from projectkoios.references.path_safety import (
    AuthorizedRoot,
    validate_citekey,
    validate_relative_path,
    validate_root_alias,
)


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
        validate_root_alias(self.alias, field="search-root alias")
        if not isinstance(self.path, Path):
            raise ValueError("search-root path must be a Path")


@dataclass(frozen=True)
class AssetCandidate:
    candidate_id: str
    proposed_citekey: str
    identity_status: str
    citekey_status: str
    root_alias: str
    relative_path: str
    score: float
    evidence: tuple[str, ...]
    recommendation: str
    sha256: str
    byte_size: int

    def __post_init__(self) -> None:
        if (
            re.fullmatch(
                r"reference-candidate:sha256:[0-9a-f]{64}",
                self.candidate_id,
            )
            is None
        ):
            raise ValueError("asset candidate identity is invalid")
        validate_citekey(
            self.proposed_citekey,
            field="proposed citekey",
        )
        if self.identity_status != "unaccepted-candidate":
            raise ValueError("asset candidate cannot claim accepted identity")
        if self.citekey_status != "proposed-noncanonical":
            raise ValueError("asset candidate citekey must be noncanonical")
        validate_root_alias(self.root_alias)
        validate_relative_path(self.relative_path)
        if re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ValueError("asset candidate SHA-256 must be lowercase hex")
        if type(self.byte_size) is not int or self.byte_size <= 0:
            raise ValueError("asset candidate byte size must be positive")

    @property
    def materialized_filename(self) -> str:
        digest = self.candidate_id.rsplit(":", maxsplit=1)[-1]
        return f"{self.proposed_citekey}.candidate-{digest[:16]}.pdf"


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
                    candidate_id=item["candidate_id"],
                    proposed_citekey=item["proposed_citekey"],
                    identity_status=item["identity_status"],
                    citekey_status=item["citekey_status"],
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
        records: tuple[ReferenceCandidate, ...],
        roots: tuple[SearchRoot, ...],
    ) -> AssetDiscoveryPlan:
        candidates: list[AssetCandidate] = []
        authorized = _authorized_roots(roots)
        for root in roots:
            safe_root = authorized[root.alias]
            for relative in safe_root.iter_files(suffix=".pdf", recursive=True):
                path = safe_root.child_path(relative)
                matches: list[
                    tuple[ReferenceCandidate, float, tuple[str, ...]]
                ] = []
                for record in records:
                    score, evidence = self._score(record, path)
                    if score >= 0.5:
                        matches.append((record, score, evidence))
                if not matches:
                    continue
                content = safe_root.read_bytes(relative)
                digest = hashlib.sha256(content).hexdigest()
                for record, score, evidence in matches:
                    candidates.append(
                        AssetCandidate(
                            candidate_id=record.candidate_id,
                            proposed_citekey=record.proposed_citekey,
                            identity_status=record.lifecycle_status,
                            citekey_status=record.citekey_status,
                            root_alias=root.alias,
                            relative_path=relative.as_posix(),
                            score=score,
                            evidence=evidence,
                            recommendation=(
                                "strong-candidate"
                                if score >= 0.9
                                else "manual-review"
                            ),
                            sha256=digest,
                            byte_size=len(content),
                        )
                    )
        ordered = tuple(
            sorted(
                candidates,
                key=lambda item: (
                    item.proposed_citekey,
                    item.candidate_id,
                    -item.score,
                    item.root_alias,
                    item.relative_path,
                ),
            )
        )
        return AssetDiscoveryPlan(schema_version=1, candidates=ordered)

    @staticmethod
    def _score(
        record: ReferenceCandidate,
        path: Path,
    ) -> tuple[float, tuple[str, ...]]:
        stem_words = _normalized_words(path.stem)
        stem_joined = "".join(stem_words)
        key_joined = "".join(_normalized_words(record.proposed_citekey))
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
    root_paths = _authorized_roots(roots)
    if candidate.root_alias not in root_paths:
        raise ValueError("candidate search-root alias was not supplied")
    relative = validate_relative_path(candidate.relative_path)
    content = root_paths[candidate.root_alias].read_bytes(relative)
    if hashlib.sha256(content).hexdigest() != candidate.sha256:
        raise ValueError("candidate source hash changed after planning")
    if len(content) != candidate.byte_size:
        raise ValueError("candidate source size changed after planning")

    destination_root = AuthorizedRoot.create(
        destination_directory,
        label="asset destination root",
    )
    filename = candidate.materialized_filename
    state = destination_root.state(filename)
    destination = destination_root.child_path(filename)
    if state == "regular":
        if (
            hashlib.sha256(destination_root.read_bytes(filename)).hexdigest()
            == candidate.sha256
        ):
            return destination
        raise FileExistsError(
            f"destination exists with different bytes: {destination}"
        )
    if state != "missing":
        raise FileExistsError(f"destination is not a file: {destination}")
    return destination_root.write_bytes(filename, content, replace=False)


def _authorized_roots(
    roots: tuple[SearchRoot, ...],
) -> dict[str, AuthorizedRoot]:
    if not roots:
        raise ValueError("at least one search root is required")
    aliases = tuple(root.alias for root in roots)
    if len(aliases) != len(set(aliases)):
        raise ValueError("search-root aliases must be unique")
    return {
        root.alias: AuthorizedRoot.existing(
            root.path,
            label=f"search root {root.alias!r}",
        )
        for root in roots
    }
