from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class MetadataEnrichment:
    provider: str
    source_url: str
    retrieved_at: str
    doi: str
    title: str | None
    authors: tuple[str, ...]
    year: str | None
    abstract: str | None
    abstract_hash: str | None
    abstract_status: str


class CrossrefClient:
    def __init__(
        self,
        *,
        mailto: str | None = None,
        cache_directory: Path | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.mailto = mailto
        self.cache_directory = cache_directory
        self.timeout_seconds = timeout_seconds

    def fetch(self, doi: str) -> MetadataEnrichment:
        normalized = doi.strip().lower()
        cache_path = self._cache_path(normalized)
        if cache_path is not None and cache_path.exists():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            url = f"https://api.crossref.org/works/{quote(normalized, safe='')}"
            headers = {"User-Agent": self._user_agent()}
            with urlopen(  # noqa: S310 - fixed HTTPS API origin
                Request(url, headers=headers), timeout=self.timeout_seconds
            ) as response:
                payload = json.load(response)
            if cache_path is not None:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
        return self._to_enrichment(normalized, payload)

    def _cache_path(self, doi: str) -> Path | None:
        if self.cache_directory is None:
            return None
        digest = hashlib.sha256(doi.encode()).hexdigest()
        return self.cache_directory / "crossref" / f"{digest}.json"

    def _user_agent(self) -> str:
        agent = "projectkoios-references/0.0.0"
        if self.mailto:
            return f"{agent} (mailto:{self.mailto})"
        return agent

    @staticmethod
    def _to_enrichment(
        doi: str,
        payload: dict[str, object],
    ) -> MetadataEnrichment:
        message = payload.get("message")
        if not isinstance(message, dict):
            raise ValueError("Crossref response has no message object")
        titles = message.get("title", [])
        title = str(titles[0]) if isinstance(titles, list) and titles else None
        authors: list[str] = []
        raw_authors = message.get("author", [])
        if isinstance(raw_authors, list):
            for person in raw_authors:
                if isinstance(person, dict):
                    name = " ".join(
                        str(person.get(field, "")).strip()
                        for field in ("given", "family")
                    ).strip()
                    if name:
                        authors.append(name)
        year: str | None = None
        issued = message.get("issued")
        if isinstance(issued, dict):
            date_parts = issued.get("date-parts")
            if (
                isinstance(date_parts, list)
                and date_parts
                and isinstance(date_parts[0], list)
                and date_parts[0]
            ):
                year = str(date_parts[0][0])

        raw_abstract = message.get("abstract")
        abstract: str | None = None
        if isinstance(raw_abstract, str) and raw_abstract.strip():
            abstract = " ".join(
                html.unescape(_TAG.sub(" ", raw_abstract)).split()
            )
        source_url = f"https://api.crossref.org/works/{quote(doi, safe='')}"
        return MetadataEnrichment(
            provider="crossref",
            source_url=source_url,
            retrieved_at=datetime.now(UTC).isoformat(),
            doi=doi,
            title=title,
            authors=tuple(authors),
            year=year,
            abstract=abstract,
            abstract_hash=(
                hashlib.sha256(abstract.encode()).hexdigest()
                if abstract is not None
                else None
            ),
            abstract_status=(
                "provider-supplied" if abstract is not None else "not-available"
            ),
        )
