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

from projectkoios.references.path_safety import AuthorizedRoot

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
        self._cache_root: AuthorizedRoot | None = None
        if cache_directory is not None:
            root = AuthorizedRoot.create(
                cache_directory,
                label="provider cache root",
            )
            state = root.state("crossref")
            if state == "missing":
                self._cache_root = root.create_directory("crossref")
            elif state == "directory":
                self._cache_root = AuthorizedRoot.existing(
                    root.child_path("crossref"),
                    label="Crossref cache root",
                )
            else:
                raise ValueError("Crossref cache path is not a directory")

    def fetch(self, doi: str) -> MetadataEnrichment:
        normalized = doi.strip().lower()
        cache_key = self._cache_key(normalized)
        if (
            cache_key is not None
            and self._cache_root is not None
            and self._cache_root.state(cache_key) == "regular"
        ):
            payload = json.loads(self._cache_root.read_text(cache_key))
        else:
            url = f"https://api.crossref.org/works/{quote(normalized, safe='')}"
            headers = {"User-Agent": self._user_agent()}
            with urlopen(  # noqa: S310 - fixed HTTPS API origin
                Request(url, headers=headers), timeout=self.timeout_seconds
            ) as response:
                payload = json.load(response)
            if cache_key is not None and self._cache_root is not None:
                rendered = (
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
                ).encode("utf-8")
                try:
                    self._cache_root.write_bytes(
                        cache_key,
                        rendered,
                        replace=False,
                    )
                except FileExistsError:
                    pass
        return self._to_enrichment(normalized, payload)

    def _cache_key(self, doi: str) -> str | None:
        if self._cache_root is None:
            return None
        digest = hashlib.sha256(doi.encode()).hexdigest()
        return f"{digest}.json"

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
