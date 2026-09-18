from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
from typing import Any, Self, cast

from projectkoios.references.models import normalize_doi
from projectkoios.references.path_safety import (
    validate_citekey,
    validate_relative_path,
)

_IDENTITY_SCHEMA_VERSION = 1
_MAX_TEXT = 4096
_MAX_VERBATIM_BYTES = 1_000_000
_MAX_ITEMS = 10_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONTENT_ID = re.compile(r"^[a-z][a-z0-9.-]*:sha256:[0-9a-f]{64}$")


class IdentityRecordError(ValueError):
    """Raised when identity evidence or a decision is malformed."""


@dataclass(frozen=True)
class ProducerIdentity:
    name: str
    version: str

    def __post_init__(self) -> None:
        _bounded(self.name, field="producer name")
        _bounded(self.version, field="producer version")

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _exact_object(
            value,
            fields={"name", "version"},
            label="producer identity",
        )
        return cls(
            name=_required_string(data["name"], field="producer name"),
            version=_required_string(data["version"], field="producer version"),
        )


@dataclass(frozen=True)
class SourceBibliographyObservation:
    """One exact source entry observed without accepting its metadata."""

    schema_version: int
    authority_kind: str
    source_id: str
    asserted_source_revision: str | None
    source_path: str
    bibliography_sha256: str
    bibliography_byte_size: int
    entry_index: int
    observed_citekey: str
    verbatim_entry: str
    parser: ProducerIdentity
    observation_id: str

    def __post_init__(self) -> None:
        if self.schema_version != _IDENTITY_SCHEMA_VERSION:
            raise IdentityRecordError(
                "unsupported source-observation schema version"
            )
        if self.authority_kind != "source-bibliography-observation":
            raise IdentityRecordError("unsupported source-observation kind")
        _bounded(self.source_id, field="source_id")
        if self.asserted_source_revision is not None:
            _bounded(
                self.asserted_source_revision,
                field="asserted_source_revision",
            )
        validate_relative_path(self.source_path, field="source_path")
        _validate_sha256(self.bibliography_sha256, field="bibliography_sha256")
        if type(self.bibliography_byte_size) is not int or (
            self.bibliography_byte_size <= 0
        ):
            raise IdentityRecordError(
                "bibliography_byte_size must be a positive integer"
            )
        if type(self.entry_index) is not int or self.entry_index < 0:
            raise IdentityRecordError(
                "entry_index must be a non-negative integer"
            )
        validate_citekey(self.observed_citekey, field="observed citekey")
        _bounded(
            self.verbatim_entry,
            field="verbatim_entry",
            max_bytes=_MAX_VERBATIM_BYTES,
        )
        if len(self.verbatim_entry.encode("utf-8")) > (
            self.bibliography_byte_size
        ):
            raise IdentityRecordError(
                "verbatim entry exceeds its source bibliography size"
            )
        if not isinstance(self.parser, ProducerIdentity):
            raise IdentityRecordError("observation parser identity is invalid")
        expected = self.identity_for(
            schema_version=self.schema_version,
            authority_kind=self.authority_kind,
            source_id=self.source_id,
            asserted_source_revision=self.asserted_source_revision,
            source_path=self.source_path,
            bibliography_sha256=self.bibliography_sha256,
            bibliography_byte_size=self.bibliography_byte_size,
            entry_index=self.entry_index,
            observed_citekey=self.observed_citekey,
            verbatim_entry=self.verbatim_entry,
            parser=self.parser,
        )
        if self.observation_id != expected:
            raise IdentityRecordError(
                "source-observation identity does not match"
            )

    @classmethod
    def create(
        cls,
        *,
        source_id: str,
        asserted_source_revision: str | None,
        source_path: str,
        bibliography_bytes: bytes,
        entry_index: int,
        observed_citekey: str,
        verbatim_entry: str,
        parser: ProducerIdentity,
    ) -> Self:
        if not isinstance(bibliography_bytes, bytes) or not bibliography_bytes:
            raise IdentityRecordError(
                "bibliography_bytes must be non-empty bytes"
            )
        try:
            verbatim_bytes = verbatim_entry.encode("utf-8")
        except UnicodeEncodeError as error:
            raise IdentityRecordError(
                "verbatim_entry must be UTF-8 encodable"
            ) from error
        if verbatim_bytes not in bibliography_bytes:
            raise IdentityRecordError(
                "verbatim_entry is not present in bibliography bytes"
            )
        payload = {
            "schema_version": _IDENTITY_SCHEMA_VERSION,
            "authority_kind": "source-bibliography-observation",
            "source_id": source_id,
            "asserted_source_revision": asserted_source_revision,
            "source_path": source_path,
            "bibliography_sha256": hashlib.sha256(
                bibliography_bytes
            ).hexdigest(),
            "bibliography_byte_size": len(bibliography_bytes),
            "entry_index": entry_index,
            "observed_citekey": observed_citekey,
            "verbatim_entry": verbatim_entry,
            "parser": parser,
        }
        return cls(
            schema_version=_IDENTITY_SCHEMA_VERSION,
            authority_kind="source-bibliography-observation",
            source_id=source_id,
            asserted_source_revision=asserted_source_revision,
            source_path=source_path,
            bibliography_sha256=cast(str, payload["bibliography_sha256"]),
            bibliography_byte_size=len(bibliography_bytes),
            entry_index=entry_index,
            observed_citekey=observed_citekey,
            verbatim_entry=verbatim_entry,
            parser=parser,
            observation_id=cls.identity_for(**payload),
        )

    @classmethod
    def from_json(cls, text: str) -> Self:
        data = _canonical_object(text, label="source observation")
        value = cls.from_dict(data)
        if value.to_json() != text:
            raise IdentityRecordError(
                "source-observation serialization is not canonical"
            )
        return value

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _exact_object(
            value,
            fields={
                "schema_version",
                "authority_kind",
                "source_id",
                "asserted_source_revision",
                "source_path",
                "bibliography_sha256",
                "bibliography_byte_size",
                "entry_index",
                "observed_citekey",
                "verbatim_entry",
                "parser",
                "observation_id",
            },
            label="source observation",
        )
        revision = data["asserted_source_revision"]
        if revision is not None and not isinstance(revision, str):
            raise IdentityRecordError(
                "asserted_source_revision must be a string or null"
            )
        return cls(
            schema_version=_required_int(
                data["schema_version"], field="schema_version"
            ),
            authority_kind=_required_string(
                data["authority_kind"], field="authority_kind"
            ),
            source_id=_required_string(data["source_id"], field="source_id"),
            asserted_source_revision=cast(str | None, revision),
            source_path=_required_string(
                data["source_path"], field="source_path"
            ),
            bibliography_sha256=_required_string(
                data["bibliography_sha256"], field="bibliography_sha256"
            ),
            bibliography_byte_size=_required_int(
                data["bibliography_byte_size"],
                field="bibliography_byte_size",
            ),
            entry_index=_required_int(data["entry_index"], field="entry_index"),
            observed_citekey=_required_string(
                data["observed_citekey"], field="observed_citekey"
            ),
            verbatim_entry=_required_string(
                data["verbatim_entry"], field="verbatim_entry"
            ),
            parser=ProducerIdentity.from_dict(data["parser"]),
            observation_id=_required_string(
                data["observation_id"], field="observation_id"
            ),
        )

    @staticmethod
    def identity_for(**payload: object) -> str:
        return _stable_id("bibliography-observation", payload)

    def to_json(self) -> str:
        return _pretty_json(self)


@dataclass(frozen=True)
class ReferenceCandidate:
    """A normalized noncanonical proposal linked to exact observations."""

    schema_version: int
    authority_kind: str
    lifecycle_status: str
    proposed_citekey: str
    citekey_status: str
    entry_type: str
    title: str | None
    authors: tuple[str, ...]
    year: str | None
    doi: str | None
    isbn: str | None
    url: str | None
    eprint: str | None
    source_observation_ids: tuple[str, ...]
    generator: ProducerIdentity
    candidate_id: str

    def __post_init__(self) -> None:
        if self.schema_version != _IDENTITY_SCHEMA_VERSION:
            raise IdentityRecordError("unsupported candidate schema version")
        if self.authority_kind != "reference-candidate":
            raise IdentityRecordError("unsupported candidate authority kind")
        if self.lifecycle_status != "unaccepted-candidate":
            raise IdentityRecordError("candidate cannot claim accepted status")
        if self.citekey_status != "proposed-noncanonical":
            raise IdentityRecordError("candidate citekey must be noncanonical")
        validate_citekey(self.proposed_citekey, field="proposed citekey")
        _bounded(self.entry_type, field="entry_type")
        _optional_bounded(self.title, field="title")
        _string_tuple(self.authors, field="authors", sorted_unique=False)
        _optional_bounded(self.year, field="year")
        for field_name, value in (
            ("doi", self.doi),
            ("isbn", self.isbn),
            ("url", self.url),
            ("eprint", self.eprint),
        ):
            _optional_bounded(value, field=field_name)
        if normalize_doi(self.doi) != self.doi:
            raise IdentityRecordError("candidate DOI must be normalized")
        _content_id_tuple(
            self.source_observation_ids,
            field="source_observation_ids",
        )
        if not self.source_observation_ids:
            raise IdentityRecordError(
                "candidate requires source-observation evidence"
            )
        if not isinstance(self.generator, ProducerIdentity):
            raise IdentityRecordError("candidate generator identity is invalid")
        expected = self.identity_for(
            schema_version=self.schema_version,
            authority_kind=self.authority_kind,
            lifecycle_status=self.lifecycle_status,
            proposed_citekey=self.proposed_citekey,
            citekey_status=self.citekey_status,
            entry_type=self.entry_type,
            title=self.title,
            authors=self.authors,
            year=self.year,
            doi=self.doi,
            isbn=self.isbn,
            url=self.url,
            eprint=self.eprint,
            source_observation_ids=self.source_observation_ids,
            generator=self.generator,
        )
        if self.candidate_id != expected:
            raise IdentityRecordError("candidate identity does not match")

    @classmethod
    def create(
        cls,
        *,
        proposed_citekey: str,
        entry_type: str,
        title: str | None,
        authors: tuple[str, ...],
        year: str | None,
        source_observation_ids: tuple[str, ...],
        generator: ProducerIdentity,
        doi: str | None = None,
        isbn: str | None = None,
        url: str | None = None,
        eprint: str | None = None,
    ) -> Self:
        payload = {
            "schema_version": _IDENTITY_SCHEMA_VERSION,
            "authority_kind": "reference-candidate",
            "lifecycle_status": "unaccepted-candidate",
            "proposed_citekey": proposed_citekey,
            "citekey_status": "proposed-noncanonical",
            "entry_type": entry_type,
            "title": title,
            "authors": authors,
            "year": year,
            "doi": normalize_doi(doi),
            "isbn": isbn,
            "url": url,
            "eprint": eprint,
            "source_observation_ids": tuple(sorted(source_observation_ids)),
            "generator": generator,
        }
        return cls(
            schema_version=_IDENTITY_SCHEMA_VERSION,
            authority_kind="reference-candidate",
            lifecycle_status="unaccepted-candidate",
            proposed_citekey=proposed_citekey,
            citekey_status="proposed-noncanonical",
            entry_type=entry_type,
            title=title,
            authors=authors,
            year=year,
            doi=normalize_doi(doi),
            isbn=isbn,
            url=url,
            eprint=eprint,
            source_observation_ids=tuple(sorted(source_observation_ids)),
            generator=generator,
            candidate_id=cls.identity_for(**payload),
        )

    @classmethod
    def from_json(cls, text: str) -> Self:
        data = _canonical_object(text, label="reference candidate")
        value = cls.from_dict(data)
        if value.to_json() != text:
            raise IdentityRecordError(
                "candidate serialization is not canonical"
            )
        return value

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _exact_object(
            value,
            fields={
                "schema_version",
                "authority_kind",
                "lifecycle_status",
                "proposed_citekey",
                "citekey_status",
                "entry_type",
                "title",
                "authors",
                "year",
                "doi",
                "isbn",
                "url",
                "eprint",
                "source_observation_ids",
                "generator",
                "candidate_id",
            },
            label="reference candidate",
        )
        return cls(
            schema_version=_required_int(
                data["schema_version"], field="schema_version"
            ),
            authority_kind=_required_string(
                data["authority_kind"], field="authority_kind"
            ),
            lifecycle_status=_required_string(
                data["lifecycle_status"], field="lifecycle_status"
            ),
            proposed_citekey=_required_string(
                data["proposed_citekey"], field="proposed_citekey"
            ),
            citekey_status=_required_string(
                data["citekey_status"], field="citekey_status"
            ),
            entry_type=_required_string(data["entry_type"], field="entry_type"),
            title=_optional_string(data["title"], field="title"),
            authors=_string_array(data["authors"], field="authors"),
            year=_optional_string(data["year"], field="year"),
            doi=_optional_string(data["doi"], field="doi"),
            isbn=_optional_string(data["isbn"], field="isbn"),
            url=_optional_string(data["url"], field="url"),
            eprint=_optional_string(data["eprint"], field="eprint"),
            source_observation_ids=_string_array(
                data["source_observation_ids"],
                field="source_observation_ids",
            ),
            generator=ProducerIdentity.from_dict(data["generator"]),
            candidate_id=_required_string(
                data["candidate_id"], field="candidate_id"
            ),
        )

    @staticmethod
    def identity_for(**payload: object) -> str:
        return _stable_id("reference-candidate", payload)

    def to_json(self) -> str:
        return _pretty_json(self)


@dataclass(frozen=True)
class LegacySeedMapping:
    schema_version: int
    authority_kind: str
    legacy_citekey: str
    candidate_id: str
    source_observation_id: str
    canonical_authority: str
    mapping_id: str

    def __post_init__(self) -> None:
        if self.schema_version != _IDENTITY_SCHEMA_VERSION:
            raise IdentityRecordError("unsupported legacy-mapping schema")
        if self.authority_kind != "legacy-seed-candidate-mapping":
            raise IdentityRecordError("unsupported legacy-mapping kind")
        validate_citekey(self.legacy_citekey, field="legacy citekey")
        _validate_content_id(self.candidate_id, field="candidate_id")
        _validate_content_id(
            self.source_observation_id,
            field="source_observation_id",
        )
        if self.canonical_authority != "not-established":
            raise IdentityRecordError(
                "legacy mapping cannot establish canonical authority"
            )
        expected = _stable_id(
            "legacy-seed-mapping",
            {
                "schema_version": self.schema_version,
                "authority_kind": self.authority_kind,
                "legacy_citekey": self.legacy_citekey,
                "candidate_id": self.candidate_id,
                "source_observation_id": self.source_observation_id,
                "canonical_authority": self.canonical_authority,
            },
        )
        if self.mapping_id != expected:
            raise IdentityRecordError("legacy mapping identity does not match")

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _exact_object(
            value,
            fields={
                "schema_version",
                "authority_kind",
                "legacy_citekey",
                "candidate_id",
                "source_observation_id",
                "canonical_authority",
                "mapping_id",
            },
            label="legacy seed mapping",
        )
        return cls(
            schema_version=_required_int(
                data["schema_version"], field="schema_version"
            ),
            authority_kind=_required_string(
                data["authority_kind"], field="authority_kind"
            ),
            legacy_citekey=_required_string(
                data["legacy_citekey"], field="legacy_citekey"
            ),
            candidate_id=_required_string(
                data["candidate_id"], field="candidate_id"
            ),
            source_observation_id=_required_string(
                data["source_observation_id"],
                field="source_observation_id",
            ),
            canonical_authority=_required_string(
                data["canonical_authority"],
                field="canonical_authority",
            ),
            mapping_id=_required_string(data["mapping_id"], field="mapping_id"),
        )

    @classmethod
    def from_json(cls, text: str) -> Self:
        data = _canonical_object(text, label="legacy seed mapping")
        value = cls.from_dict(data)
        if value.to_json() != text:
            raise IdentityRecordError(
                "legacy seed mapping serialization is not canonical"
            )
        return value

    @classmethod
    def from_candidate(cls, candidate: ReferenceCandidate) -> Self:
        source_id = candidate.source_observation_ids[0]
        payload = {
            "schema_version": _IDENTITY_SCHEMA_VERSION,
            "authority_kind": "legacy-seed-candidate-mapping",
            "legacy_citekey": candidate.proposed_citekey,
            "candidate_id": candidate.candidate_id,
            "source_observation_id": source_id,
            "canonical_authority": "not-established",
        }
        return cls(
            schema_version=_IDENTITY_SCHEMA_VERSION,
            authority_kind="legacy-seed-candidate-mapping",
            legacy_citekey=candidate.proposed_citekey,
            candidate_id=candidate.candidate_id,
            source_observation_id=source_id,
            canonical_authority="not-established",
            mapping_id=_stable_id("legacy-seed-mapping", payload),
        )

    def to_json(self) -> str:
        return _pretty_json(self)


class ActorKind(StrEnum):
    PERSON = "person"


class ActorAuthorityScope(StrEnum):
    REFERENCE_IDENTITY_CURATOR = "reference-identity-curator"


@dataclass(frozen=True)
class ActorProvenance:
    actor_id: str
    actor_kind: ActorKind
    authority_scope: ActorAuthorityScope
    verification_record_id: str
    verification_method: str

    def __post_init__(self) -> None:
        _bounded(self.actor_id, field="actor_id")
        if self.actor_kind is not ActorKind.PERSON:
            raise IdentityRecordError(
                "canonical identity decisions require a person actor"
            )
        if not isinstance(self.authority_scope, ActorAuthorityScope):
            raise IdentityRecordError("unsupported actor authority scope")
        _validate_content_id(
            self.verification_record_id,
            field="actor verification record",
        )
        _bounded(self.verification_method, field="verification_method")

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _exact_object(
            value,
            fields={
                "actor_id",
                "actor_kind",
                "authority_scope",
                "verification_record_id",
                "verification_method",
            },
            label="actor provenance",
        )
        return cls(
            actor_id=_required_string(data["actor_id"], field="actor_id"),
            actor_kind=ActorKind(
                _required_string(data["actor_kind"], field="actor_kind")
            ),
            authority_scope=ActorAuthorityScope(
                _required_string(
                    data["authority_scope"], field="authority_scope"
                )
            ),
            verification_record_id=_required_string(
                data["verification_record_id"],
                field="verification_record_id",
            ),
            verification_method=_required_string(
                data["verification_method"], field="verification_method"
            ),
        )


class IdentityDecisionKind(StrEnum):
    PROMOTION = "promotion"
    MERGE = "merge"
    SPLIT = "split"
    ALIAS = "alias"
    CITEKEY_MIGRATION = "citekey-migration"


@dataclass(frozen=True)
class CanonicalPlan:
    canonical_citekey: str
    candidate_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_citekey(self.canonical_citekey, field="canonical citekey")
        _content_id_tuple(self.candidate_ids, field="plan candidate_ids")
        if not self.candidate_ids:
            raise IdentityRecordError("canonical plan needs candidates")

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _exact_object(
            value,
            fields={"canonical_citekey", "candidate_ids"},
            label="canonical plan",
        )
        return cls(
            canonical_citekey=_required_string(
                data["canonical_citekey"], field="canonical_citekey"
            ),
            candidate_ids=_string_array(
                data["candidate_ids"], field="candidate_ids"
            ),
        )


@dataclass(frozen=True)
class IdentityDecision:
    schema_version: int
    authority_kind: str
    decision_kind: IdentityDecisionKind
    actor: ActorProvenance
    evidence_ids: tuple[str, ...]
    rationale: str
    input_reference_ids: tuple[str, ...]
    outputs: tuple[CanonicalPlan, ...]
    alias_citekey: str | None
    prior_citekey: str | None
    supersedes_decision_ids: tuple[str, ...]
    decision_id: str

    def __post_init__(self) -> None:
        if self.schema_version != _IDENTITY_SCHEMA_VERSION:
            raise IdentityRecordError("unsupported identity-decision schema")
        if self.authority_kind != "canonical-identity-decision":
            raise IdentityRecordError("unsupported identity-decision kind")
        if not isinstance(self.decision_kind, IdentityDecisionKind):
            raise IdentityRecordError("invalid identity decision kind")
        if not isinstance(self.actor, ActorProvenance):
            raise IdentityRecordError("identity decision actor is invalid")
        _content_id_tuple(self.evidence_ids, field="decision evidence_ids")
        if not self.evidence_ids:
            raise IdentityRecordError("identity decision requires evidence")
        if self.actor.verification_record_id not in self.evidence_ids:
            raise IdentityRecordError(
                "decision evidence omits actor verification"
            )
        _bounded(self.rationale, field="decision rationale")
        _content_id_tuple(
            self.input_reference_ids,
            field="input_reference_ids",
        )
        if not isinstance(self.outputs, tuple) or any(
            not isinstance(item, CanonicalPlan) for item in self.outputs
        ):
            raise IdentityRecordError(
                "decision outputs must be a canonical-plan tuple"
            )
        if len(self.outputs) > _MAX_ITEMS:
            raise IdentityRecordError("decision outputs exceed limit")
        if self.alias_citekey is not None:
            validate_citekey(self.alias_citekey, field="alias citekey")
        if self.prior_citekey is not None:
            validate_citekey(self.prior_citekey, field="prior citekey")
        _content_id_tuple(
            self.supersedes_decision_ids,
            field="supersedes_decision_ids",
        )
        self._validate_shape()
        expected = self.identity_for(
            schema_version=self.schema_version,
            authority_kind=self.authority_kind,
            decision_kind=self.decision_kind,
            actor=self.actor,
            evidence_ids=self.evidence_ids,
            rationale=self.rationale,
            input_reference_ids=self.input_reference_ids,
            outputs=self.outputs,
            alias_citekey=self.alias_citekey,
            prior_citekey=self.prior_citekey,
            supersedes_decision_ids=self.supersedes_decision_ids,
        )
        if self.decision_id != expected:
            raise IdentityRecordError("identity decision ID does not match")

    def _validate_shape(self) -> None:
        if self.decision_kind is IdentityDecisionKind.PROMOTION:
            valid = (
                not self.input_reference_ids
                and len(self.outputs) == 1
                and self.alias_citekey is None
                and self.prior_citekey is None
                and not self.supersedes_decision_ids
            )
        elif self.decision_kind is IdentityDecisionKind.MERGE:
            valid = (
                len(self.input_reference_ids) >= 2
                and len(self.outputs) == 1
                and self.alias_citekey is None
                and self.prior_citekey is None
                and len(self.supersedes_decision_ids)
                == len(self.input_reference_ids)
            )
        elif self.decision_kind is IdentityDecisionKind.SPLIT:
            valid = (
                len(self.input_reference_ids) == 1
                and len(self.outputs) >= 2
                and self.alias_citekey is None
                and self.prior_citekey is None
                and len(self.supersedes_decision_ids) == 1
            )
        elif self.decision_kind is IdentityDecisionKind.ALIAS:
            valid = (
                len(self.input_reference_ids) == 1
                and not self.outputs
                and self.alias_citekey is not None
                and self.prior_citekey is None
                and len(self.supersedes_decision_ids) <= 1
            )
        else:
            valid = (
                len(self.input_reference_ids) == 1
                and len(self.outputs) == 1
                and self.alias_citekey is None
                and self.prior_citekey is not None
                and len(self.supersedes_decision_ids) == 1
            )
        if not valid:
            raise IdentityRecordError(
                f"invalid {self.decision_kind.value} decision shape"
            )

    @classmethod
    def promotion(
        cls,
        *,
        candidate_ids: tuple[str, ...],
        canonical_citekey: str,
        actor: ActorProvenance,
        evidence_ids: tuple[str, ...],
        rationale: str,
    ) -> Self:
        return cls._create(
            decision_kind=IdentityDecisionKind.PROMOTION,
            actor=actor,
            evidence_ids=evidence_ids,
            rationale=rationale,
            input_reference_ids=(),
            outputs=(CanonicalPlan(canonical_citekey, candidate_ids),),
            alias_citekey=None,
            prior_citekey=None,
            supersedes_decision_ids=(),
        )

    @classmethod
    def merge(
        cls,
        *,
        input_reference_ids: tuple[str, ...],
        candidate_ids: tuple[str, ...],
        canonical_citekey: str,
        actor: ActorProvenance,
        evidence_ids: tuple[str, ...],
        rationale: str,
        supersedes_decision_ids: tuple[str, ...],
    ) -> Self:
        return cls._create(
            decision_kind=IdentityDecisionKind.MERGE,
            actor=actor,
            evidence_ids=evidence_ids,
            rationale=rationale,
            input_reference_ids=input_reference_ids,
            outputs=(CanonicalPlan(canonical_citekey, candidate_ids),),
            alias_citekey=None,
            prior_citekey=None,
            supersedes_decision_ids=supersedes_decision_ids,
        )

    @classmethod
    def split(
        cls,
        *,
        input_reference_id: str,
        outputs: tuple[CanonicalPlan, ...],
        actor: ActorProvenance,
        evidence_ids: tuple[str, ...],
        rationale: str,
        supersedes_decision_id: str,
    ) -> Self:
        return cls._create(
            decision_kind=IdentityDecisionKind.SPLIT,
            actor=actor,
            evidence_ids=evidence_ids,
            rationale=rationale,
            input_reference_ids=(input_reference_id,),
            outputs=outputs,
            alias_citekey=None,
            prior_citekey=None,
            supersedes_decision_ids=(supersedes_decision_id,),
        )

    @classmethod
    def alias(
        cls,
        *,
        target_reference_id: str,
        alias_citekey: str,
        actor: ActorProvenance,
        evidence_ids: tuple[str, ...],
        rationale: str,
        supersedes_decision_ids: tuple[str, ...] = (),
    ) -> Self:
        return cls._create(
            decision_kind=IdentityDecisionKind.ALIAS,
            actor=actor,
            evidence_ids=evidence_ids,
            rationale=rationale,
            input_reference_ids=(target_reference_id,),
            outputs=(),
            alias_citekey=alias_citekey,
            prior_citekey=None,
            supersedes_decision_ids=supersedes_decision_ids,
        )

    @classmethod
    def migrate_citekey(
        cls,
        *,
        target_reference_id: str,
        prior_citekey: str,
        new_citekey: str,
        candidate_ids: tuple[str, ...],
        actor: ActorProvenance,
        evidence_ids: tuple[str, ...],
        rationale: str,
        supersedes_decision_id: str,
    ) -> Self:
        return cls._create(
            decision_kind=IdentityDecisionKind.CITEKEY_MIGRATION,
            actor=actor,
            evidence_ids=evidence_ids,
            rationale=rationale,
            input_reference_ids=(target_reference_id,),
            outputs=(CanonicalPlan(new_citekey, candidate_ids),),
            alias_citekey=None,
            prior_citekey=prior_citekey,
            supersedes_decision_ids=(supersedes_decision_id,),
        )

    @classmethod
    def _create(
        cls,
        *,
        decision_kind: IdentityDecisionKind,
        actor: ActorProvenance,
        evidence_ids: tuple[str, ...],
        rationale: str,
        input_reference_ids: tuple[str, ...],
        outputs: tuple[CanonicalPlan, ...],
        alias_citekey: str | None,
        prior_citekey: str | None,
        supersedes_decision_ids: tuple[str, ...],
    ) -> Self:
        payload = {
            "schema_version": _IDENTITY_SCHEMA_VERSION,
            "authority_kind": "canonical-identity-decision",
            "decision_kind": decision_kind,
            "actor": actor,
            "evidence_ids": tuple(sorted(evidence_ids)),
            "rationale": rationale,
            "input_reference_ids": tuple(sorted(input_reference_ids)),
            "outputs": tuple(
                sorted(
                    outputs,
                    key=lambda item: (
                        item.canonical_citekey,
                        item.candidate_ids,
                    ),
                )
            ),
            "alias_citekey": alias_citekey,
            "prior_citekey": prior_citekey,
            "supersedes_decision_ids": tuple(sorted(supersedes_decision_ids)),
        }
        return cls(
            schema_version=_IDENTITY_SCHEMA_VERSION,
            authority_kind="canonical-identity-decision",
            decision_kind=decision_kind,
            actor=actor,
            evidence_ids=tuple(sorted(evidence_ids)),
            rationale=rationale,
            input_reference_ids=tuple(sorted(input_reference_ids)),
            outputs=cast(tuple[CanonicalPlan, ...], payload["outputs"]),
            alias_citekey=alias_citekey,
            prior_citekey=prior_citekey,
            supersedes_decision_ids=tuple(sorted(supersedes_decision_ids)),
            decision_id=cls.identity_for(**payload),
        )

    @classmethod
    def from_json(cls, text: str) -> Self:
        data = _canonical_object(text, label="identity decision")
        value = cls.from_dict(data)
        if value.to_json() != text:
            raise IdentityRecordError(
                "identity-decision serialization is not canonical"
            )
        return value

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _exact_object(
            value,
            fields={
                "schema_version",
                "authority_kind",
                "decision_kind",
                "actor",
                "evidence_ids",
                "rationale",
                "input_reference_ids",
                "outputs",
                "alias_citekey",
                "prior_citekey",
                "supersedes_decision_ids",
                "decision_id",
            },
            label="identity decision",
        )
        outputs = data["outputs"]
        if not isinstance(outputs, list):
            raise IdentityRecordError("decision outputs must be an array")
        return cls(
            schema_version=_required_int(
                data["schema_version"], field="schema_version"
            ),
            authority_kind=_required_string(
                data["authority_kind"], field="authority_kind"
            ),
            decision_kind=IdentityDecisionKind(
                _required_string(data["decision_kind"], field="decision_kind")
            ),
            actor=ActorProvenance.from_dict(data["actor"]),
            evidence_ids=_string_array(
                data["evidence_ids"], field="evidence_ids"
            ),
            rationale=_required_string(data["rationale"], field="rationale"),
            input_reference_ids=_string_array(
                data["input_reference_ids"],
                field="input_reference_ids",
            ),
            outputs=tuple(CanonicalPlan.from_dict(item) for item in outputs),
            alias_citekey=_optional_string(
                data["alias_citekey"], field="alias_citekey"
            ),
            prior_citekey=_optional_string(
                data["prior_citekey"], field="prior_citekey"
            ),
            supersedes_decision_ids=_string_array(
                data["supersedes_decision_ids"],
                field="supersedes_decision_ids",
            ),
            decision_id=_required_string(
                data["decision_id"], field="decision_id"
            ),
        )

    @staticmethod
    def identity_for(**payload: object) -> str:
        return _stable_id("identity-decision", payload)

    def to_json(self) -> str:
        return _pretty_json(self)


class _ReplayDerived:
    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise IdentityRecordError(
            "replay-derived records can only be created by "
            "replay_identity_decisions"
        )

    def __post_init__(self) -> None:
        raise NotImplementedError


def _from_replay_record[ReplayRecord: _ReplayDerived](
    cls: type[ReplayRecord],
    **values: object,
) -> ReplayRecord:
    record = object.__new__(cls)
    for name, value in values.items():
        object.__setattr__(record, name, value)
    record.__post_init__()
    return record


@dataclass(frozen=True, init=False)
class AcceptedReference(_ReplayDerived):
    reference_id: str
    candidate_ids: tuple[str, ...]
    creating_decision_id: str

    def __post_init__(self) -> None:
        _validate_content_id(self.reference_id, field="reference_id")
        _content_id_tuple(self.candidate_ids, field="candidate_ids")
        if not self.candidate_ids:
            raise IdentityRecordError("accepted reference needs candidates")
        _validate_content_id(
            self.creating_decision_id,
            field="creating_decision_id",
        )


@dataclass(frozen=True, init=False)
class CanonicalNameBinding(_ReplayDerived):
    reference_id: str
    canonical_citekey: str
    decision_id: str
    supersedes_decision_ids: tuple[str, ...]
    active: bool

    def __post_init__(self) -> None:
        _validate_content_id(self.reference_id, field="reference_id")
        validate_citekey(self.canonical_citekey, field="canonical citekey")
        _validate_content_id(self.decision_id, field="decision_id")
        _content_id_tuple(
            self.supersedes_decision_ids,
            field="supersedes_decision_ids",
        )
        if type(self.active) is not bool:
            raise IdentityRecordError("name binding active must be boolean")


@dataclass(frozen=True, init=False)
class ReferenceAliasBinding(_ReplayDerived):
    alias_citekey: str
    target_reference_id: str
    decision_id: str
    supersedes_decision_ids: tuple[str, ...]
    active: bool
    alias_id: str

    def __post_init__(self) -> None:
        validate_citekey(self.alias_citekey, field="alias citekey")
        _validate_content_id(
            self.target_reference_id,
            field="target_reference_id",
        )
        _validate_content_id(self.decision_id, field="decision_id")
        _content_id_tuple(
            self.supersedes_decision_ids,
            field="supersedes_decision_ids",
        )
        if type(self.active) is not bool:
            raise IdentityRecordError("alias binding active must be boolean")
        expected = _stable_id(
            "reference-alias",
            {
                "alias_citekey": self.alias_citekey,
                "target_reference_id": self.target_reference_id,
                "decision_id": self.decision_id,
                "supersedes_decision_ids": self.supersedes_decision_ids,
            },
        )
        if self.alias_id != expected:
            raise IdentityRecordError("alias identity does not match")


@dataclass(frozen=True, init=False)
class ReferenceSupersession(_ReplayDerived):
    source_reference_id: str
    target_reference_ids: tuple[str, ...]
    decision_id: str

    def __post_init__(self) -> None:
        _validate_content_id(
            self.source_reference_id,
            field="source_reference_id",
        )
        _content_id_tuple(
            self.target_reference_ids,
            field="target_reference_ids",
        )
        if not self.target_reference_ids:
            raise IdentityRecordError("supersession needs target references")
        _validate_content_id(self.decision_id, field="decision_id")


@dataclass(frozen=True, init=False)
class IdentityProjection(_ReplayDerived):
    schema_version: int
    authority_kind: str
    candidates: tuple[ReferenceCandidate, ...]
    decisions: tuple[IdentityDecision, ...]
    accepted_references: tuple[AcceptedReference, ...]
    name_history: tuple[CanonicalNameBinding, ...]
    alias_history: tuple[ReferenceAliasBinding, ...]
    supersessions: tuple[ReferenceSupersession, ...]
    active_reference_ids: tuple[str, ...]
    projection_id: str

    def __post_init__(self) -> None:
        if self.schema_version != _IDENTITY_SCHEMA_VERSION:
            raise IdentityRecordError("unsupported identity-projection schema")
        if self.authority_kind != "canonical-identity-projection":
            raise IdentityRecordError("unsupported identity-projection kind")
        typed_tuples = (
            (self.candidates, ReferenceCandidate, "candidates"),
            (self.decisions, IdentityDecision, "decisions"),
            (
                self.accepted_references,
                AcceptedReference,
                "accepted_references",
            ),
            (self.name_history, CanonicalNameBinding, "name_history"),
            (self.alias_history, ReferenceAliasBinding, "alias_history"),
            (
                self.supersessions,
                ReferenceSupersession,
                "supersessions",
            ),
        )
        for values, expected_type, label in typed_tuples:
            if not isinstance(values, tuple) or any(
                not isinstance(item, expected_type) for item in values
            ):
                raise IdentityRecordError(
                    f"projection {label} must be a typed tuple"
                )
        _content_id_tuple(
            self.active_reference_ids,
            field="active_reference_ids",
        )
        payload = {
            "schema_version": self.schema_version,
            "authority_kind": self.authority_kind,
            "candidates": self.candidates,
            "decisions": self.decisions,
            "accepted_references": self.accepted_references,
            "name_history": self.name_history,
            "alias_history": self.alias_history,
            "supersessions": self.supersessions,
            "active_reference_ids": self.active_reference_ids,
        }
        if self.projection_id != _stable_id("identity-projection", payload):
            raise IdentityRecordError("identity projection ID does not match")

    @classmethod
    def from_json(cls, text: str) -> Self:
        data = _canonical_object(text, label="identity projection")
        _exact_object(
            data,
            fields={
                "schema_version",
                "authority_kind",
                "candidates",
                "decisions",
                "accepted_references",
                "name_history",
                "alias_history",
                "supersessions",
                "active_reference_ids",
                "projection_id",
            },
            label="identity projection",
        )
        candidates = data["candidates"]
        decisions = data["decisions"]
        if not isinstance(candidates, list) or not isinstance(decisions, list):
            raise IdentityRecordError(
                "projection candidates and decisions must be arrays"
            )
        replayed = replay_identity_decisions(
            tuple(ReferenceCandidate.from_dict(item) for item in candidates),
            tuple(IdentityDecision.from_dict(item) for item in decisions),
        )
        if replayed.to_json() != text:
            raise IdentityRecordError(
                "identity projection is tampered or noncanonical"
            )
        return cast(Self, replayed)

    def to_json(self) -> str:
        return _pretty_json(self)


def replay_identity_decisions(
    candidates: tuple[ReferenceCandidate, ...],
    decisions: tuple[IdentityDecision, ...],
) -> IdentityProjection:
    if not isinstance(candidates, tuple) or any(
        not isinstance(item, ReferenceCandidate) for item in candidates
    ):
        raise IdentityRecordError("candidates must be a candidate tuple")
    if not isinstance(decisions, tuple) or any(
        not isinstance(item, IdentityDecision) for item in decisions
    ):
        raise IdentityRecordError(
            "decisions must be an identity-decision tuple"
        )
    if len(candidates) > _MAX_ITEMS or len(decisions) > _MAX_ITEMS:
        raise IdentityRecordError("identity replay exceeds the record limit")
    candidate_by_id = {item.candidate_id: item for item in candidates}
    if len(candidate_by_id) != len(candidates):
        raise IdentityRecordError("candidate identities contain duplicates")
    decision_ids = tuple(item.decision_id for item in decisions)
    if len(decision_ids) != len(set(decision_ids)):
        raise IdentityRecordError("decision identities contain duplicates")

    references: dict[str, AcceptedReference] = {}
    active_references: set[str] = set()
    active_decision: dict[str, str] = {}
    current_name: dict[str, tuple[str, str]] = {}
    name_drafts: list[tuple[str, str, str, tuple[str, ...]]] = []
    current_alias: dict[str, tuple[str, str]] = {}
    alias_drafts: list[tuple[str, str, str, tuple[str, ...]]] = []
    supersessions: list[ReferenceSupersession] = []

    for decision in decisions:
        _validate_decision_evidence(decision)
        if decision.decision_kind is IdentityDecisionKind.PROMOTION:
            plan = decision.outputs[0]
            _require_candidates(plan.candidate_ids, candidate_by_id)
            _require_promotion_source_evidence(
                decision,
                plan.candidate_ids,
                candidate_by_id,
            )
            _reject_candidates_already_active(
                plan.candidate_ids,
                active_references,
                references,
            )
            _validate_output_keys(
                decision.outputs,
                active_references,
                current_name,
                current_alias,
            )
            _create_outputs(
                decision,
                references,
                active_references,
                active_decision,
                current_name,
                name_drafts,
            )
        elif decision.decision_kind is IdentityDecisionKind.MERGE:
            source_ids = decision.input_reference_ids
            _require_active_references(source_ids, active_references)
            _require_exact_supersession(
                decision,
                tuple(active_decision[item] for item in source_ids),
            )
            expected_candidates = tuple(
                sorted(
                    {
                        candidate_id
                        for reference_id in source_ids
                        for candidate_id in references[
                            reference_id
                        ].candidate_ids
                    }
                )
            )
            if decision.outputs[0].candidate_ids != expected_candidates:
                raise IdentityRecordError(
                    "merge output does not preserve source candidates"
                )
            for source_id in source_ids:
                active_references.remove(source_id)
            _validate_output_keys(
                decision.outputs,
                active_references,
                current_name,
                current_alias,
            )
            new_ids = _create_outputs(
                decision,
                references,
                active_references,
                active_decision,
                current_name,
                name_drafts,
            )
            for source_id in source_ids:
                supersessions.append(
                    _from_replay_record(
                        ReferenceSupersession,
                        source_reference_id=source_id,
                        target_reference_ids=tuple(sorted(new_ids)),
                        decision_id=decision.decision_id,
                    )
                )
        elif decision.decision_kind is IdentityDecisionKind.SPLIT:
            source_id = decision.input_reference_ids[0]
            _require_active_references((source_id,), active_references)
            _require_exact_supersession(
                decision,
                (active_decision[source_id],),
            )
            source_candidates = references[source_id].candidate_ids
            output_candidates = tuple(
                candidate_id
                for plan in decision.outputs
                for candidate_id in plan.candidate_ids
            )
            if len(output_candidates) != len(set(output_candidates)) or tuple(
                sorted(output_candidates)
            ) != tuple(sorted(source_candidates)):
                raise IdentityRecordError(
                    "split outputs must partition source candidates"
                )
            active_references.remove(source_id)
            _validate_output_keys(
                decision.outputs,
                active_references,
                current_name,
                current_alias,
            )
            new_ids = _create_outputs(
                decision,
                references,
                active_references,
                active_decision,
                current_name,
                name_drafts,
            )
            supersessions.append(
                _from_replay_record(
                    ReferenceSupersession,
                    source_reference_id=source_id,
                    target_reference_ids=tuple(sorted(new_ids)),
                    decision_id=decision.decision_id,
                )
            )
        elif decision.decision_kind is IdentityDecisionKind.ALIAS:
            target = decision.input_reference_ids[0]
            _require_active_references((target,), active_references)
            alias = cast(str, decision.alias_citekey)
            existing = current_alias.get(alias)
            expected = () if existing is None else (existing[1],)
            _require_exact_supersession(decision, expected)
            _assert_alias_available(
                alias,
                target,
                active_references,
                current_name,
            )
            current_alias[alias] = (target, decision.decision_id)
            alias_drafts.append(
                (
                    alias,
                    target,
                    decision.decision_id,
                    decision.supersedes_decision_ids,
                )
            )
        else:
            target = decision.input_reference_ids[0]
            _require_active_references((target,), active_references)
            _require_exact_supersession(
                decision,
                (active_decision[target],),
            )
            prior_name = current_name[target][0]
            if decision.prior_citekey != prior_name:
                raise IdentityRecordError(
                    "citekey migration prior name is not current"
                )
            plan = decision.outputs[0]
            if plan.candidate_ids != references[target].candidate_ids:
                raise IdentityRecordError(
                    "citekey migration cannot change candidate identity"
                )
            _assert_new_key_available(
                plan.canonical_citekey,
                target,
                active_references,
                current_name,
                current_alias,
            )
            current_name[target] = (
                plan.canonical_citekey,
                decision.decision_id,
            )
            active_decision[target] = decision.decision_id
            name_drafts.append(
                (
                    target,
                    plan.canonical_citekey,
                    decision.decision_id,
                    decision.supersedes_decision_ids,
                )
            )
            existing_alias = current_alias.get(prior_name)
            if existing_alias is not None:
                raise IdentityRecordError(
                    "prior citekey already has an active alias decision"
                )
            current_alias[prior_name] = (target, decision.decision_id)
            alias_drafts.append(
                (
                    prior_name,
                    target,
                    decision.decision_id,
                    (),
                )
            )

    accepted = tuple(
        sorted(references.values(), key=lambda item: item.reference_id)
    )
    active_ids = tuple(sorted(active_references))
    names = tuple(
        _from_replay_record(
            CanonicalNameBinding,
            reference_id=reference_id,
            canonical_citekey=citekey,
            decision_id=decision_id,
            supersedes_decision_ids=supersedes,
            active=(
                reference_id in active_references
                and current_name.get(reference_id) == (citekey, decision_id)
            ),
        )
        for reference_id, citekey, decision_id, supersedes in name_drafts
    )
    aliases = tuple(
        _alias_binding(
            alias_citekey=alias,
            target_reference_id=target,
            decision_id=decision_id,
            supersedes_decision_ids=supersedes,
            active=(
                target in active_references
                and current_alias.get(alias) == (target, decision_id)
            ),
        )
        for alias, target, decision_id, supersedes in alias_drafts
    )
    ordered_candidates = tuple(
        sorted(candidates, key=lambda item: item.candidate_id)
    )
    payload = {
        "schema_version": _IDENTITY_SCHEMA_VERSION,
        "authority_kind": "canonical-identity-projection",
        "candidates": ordered_candidates,
        "decisions": decisions,
        "accepted_references": accepted,
        "name_history": names,
        "alias_history": aliases,
        "supersessions": tuple(supersessions),
        "active_reference_ids": active_ids,
    }
    return _from_replay_record(
        IdentityProjection,
        schema_version=_IDENTITY_SCHEMA_VERSION,
        authority_kind="canonical-identity-projection",
        candidates=ordered_candidates,
        decisions=decisions,
        accepted_references=accepted,
        name_history=names,
        alias_history=aliases,
        supersessions=tuple(supersessions),
        active_reference_ids=active_ids,
        projection_id=_stable_id("identity-projection", payload),
    )


def _alias_binding(
    *,
    alias_citekey: str,
    target_reference_id: str,
    decision_id: str,
    supersedes_decision_ids: tuple[str, ...],
    active: bool,
) -> ReferenceAliasBinding:
    payload = {
        "alias_citekey": alias_citekey,
        "target_reference_id": target_reference_id,
        "decision_id": decision_id,
        "supersedes_decision_ids": supersedes_decision_ids,
    }
    return _from_replay_record(
        ReferenceAliasBinding,
        alias_citekey=alias_citekey,
        target_reference_id=target_reference_id,
        decision_id=decision_id,
        supersedes_decision_ids=supersedes_decision_ids,
        active=active,
        alias_id=_stable_id("reference-alias", payload),
    )


def _create_outputs(
    decision: IdentityDecision,
    references: dict[str, AcceptedReference],
    active_references: set[str],
    active_decision: dict[str, str],
    current_name: dict[str, tuple[str, str]],
    name_drafts: list[tuple[str, str, str, tuple[str, ...]]],
) -> tuple[str, ...]:
    created: list[str] = []
    for index, plan in enumerate(decision.outputs):
        reference_id = _stable_id(
            "canonical-reference",
            {
                "creating_decision_id": decision.decision_id,
                "output_index": index,
                "candidate_ids": plan.candidate_ids,
            },
        )
        if reference_id in references:
            raise IdentityRecordError("canonical reference identity repeats")
        references[reference_id] = _from_replay_record(
            AcceptedReference,
            reference_id=reference_id,
            candidate_ids=plan.candidate_ids,
            creating_decision_id=decision.decision_id,
        )
        active_references.add(reference_id)
        active_decision[reference_id] = decision.decision_id
        current_name[reference_id] = (
            plan.canonical_citekey,
            decision.decision_id,
        )
        name_drafts.append(
            (
                reference_id,
                plan.canonical_citekey,
                decision.decision_id,
                decision.supersedes_decision_ids,
            )
        )
        created.append(reference_id)
    return tuple(created)


def _validate_decision_evidence(decision: IdentityDecision) -> None:
    required = set(decision.input_reference_ids)
    required.update(decision.supersedes_decision_ids)
    required.update(
        candidate_id
        for output in decision.outputs
        for candidate_id in output.candidate_ids
    )
    if not required <= set(decision.evidence_ids):
        raise IdentityRecordError(
            "decision evidence omits an input, candidate, or prior decision"
        )


def _require_candidates(
    candidate_ids: tuple[str, ...],
    candidates: dict[str, ReferenceCandidate],
) -> None:
    missing = sorted(set(candidate_ids) - set(candidates))
    if missing:
        raise IdentityRecordError(f"decision candidates are missing: {missing}")


def _require_promotion_source_evidence(
    decision: IdentityDecision,
    candidate_ids: tuple[str, ...],
    candidates: dict[str, ReferenceCandidate],
) -> None:
    required = {
        observation_id
        for candidate_id in candidate_ids
        for observation_id in candidates[candidate_id].source_observation_ids
    }
    if not required <= set(decision.evidence_ids):
        raise IdentityRecordError(
            "promotion evidence omits a source observation"
        )


def _reject_candidates_already_active(
    candidate_ids: tuple[str, ...],
    active_references: set[str],
    references: dict[str, AcceptedReference],
) -> None:
    active_candidates = {
        candidate_id
        for reference_id in active_references
        for candidate_id in references[reference_id].candidate_ids
    }
    overlap = sorted(set(candidate_ids) & active_candidates)
    if overlap:
        raise IdentityRecordError(
            f"candidates already have active canonical identity: {overlap}"
        )


def _require_active_references(
    reference_ids: tuple[str, ...], active_references: set[str]
) -> None:
    missing = sorted(set(reference_ids) - active_references)
    if missing:
        raise IdentityRecordError(
            f"decision references are not active: {missing}"
        )


def _require_exact_supersession(
    decision: IdentityDecision, expected: tuple[str, ...]
) -> None:
    if decision.supersedes_decision_ids != tuple(sorted(expected)):
        raise IdentityRecordError(
            "decision does not supersede the exact active decision history"
        )


def _validate_output_keys(
    plans: tuple[CanonicalPlan, ...],
    active_references: set[str],
    current_name: dict[str, tuple[str, str]],
    current_alias: dict[str, tuple[str, str]],
) -> None:
    keys = tuple(item.canonical_citekey for item in plans)
    if len(keys) != len(set(keys)):
        raise IdentityRecordError("decision outputs repeat a canonical citekey")
    active_keys = {
        current_name[reference_id][0] for reference_id in active_references
    }
    conflicts = sorted(set(keys) & (active_keys | set(current_alias)))
    if conflicts:
        raise IdentityRecordError(
            f"decision output citekeys are already active: {conflicts}"
        )


def _assert_new_key_available(
    citekey: str,
    target_reference_id: str,
    active_references: set[str],
    current_name: dict[str, tuple[str, str]],
    current_alias: dict[str, tuple[str, str]],
) -> None:
    for reference_id in active_references:
        if reference_id != target_reference_id and (
            current_name[reference_id][0] == citekey
        ):
            raise IdentityRecordError("canonical citekey is already active")
    if citekey in current_alias:
        raise IdentityRecordError("canonical citekey conflicts with an alias")


def _assert_alias_available(
    alias: str,
    target_reference_id: str,
    active_references: set[str],
    current_name: dict[str, tuple[str, str]],
) -> None:
    for reference_id in active_references:
        if current_name[reference_id][0] == alias:
            raise IdentityRecordError(
                "alias conflicts with an active canonical citekey"
            )
    if target_reference_id not in active_references:
        raise IdentityRecordError("alias target is not active")


def _stable_id(kind: str, payload: object) -> str:
    digest = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    return f"{kind}:sha256:{digest}"


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _pretty_json(value: object) -> str:
    return (
        json.dumps(
            _jsonable(value),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _jsonable(value: object) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _jsonable(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _canonical_object(text: str, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise IdentityRecordError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise IdentityRecordError(f"{label} must be an object")
    return value


def _exact_object(
    value: object, *, fields: set[str], label: str
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise IdentityRecordError(f"{label} must be an object")
    missing = fields - set(value)
    unknown = set(value) - fields
    if missing or unknown:
        raise IdentityRecordError(
            f"{label} fields differ: missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}"
        )
    return value


def _bounded(value: object, *, field: str, max_bytes: int = _MAX_TEXT) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > max_bytes
    ):
        raise IdentityRecordError(f"{field} must be bounded non-empty text")
    return value


def _optional_bounded(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _bounded(value, field=field)


def _required_string(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise IdentityRecordError(f"{field} must be a string")
    return value


def _optional_string(value: object, *, field: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise IdentityRecordError(f"{field} must be a string or null")
    return cast(str | None, value)


def _required_int(value: object, *, field: str) -> int:
    if type(value) is not int:
        raise IdentityRecordError(f"{field} must be an integer")
    return cast(int, value)


def _string_array(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) for item in value
    ):
        raise IdentityRecordError(f"{field} must be a string array")
    return tuple(value)


def _string_tuple(
    value: object, *, field: str, sorted_unique: bool = True
) -> None:
    if not isinstance(value, tuple) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise IdentityRecordError(f"{field} must be a non-empty-string tuple")
    if len(value) > _MAX_ITEMS:
        raise IdentityRecordError(f"{field} exceeds the item limit")
    if sorted_unique and (
        value != tuple(sorted(value)) or len(value) != len(set(value))
    ):
        raise IdentityRecordError(f"{field} must be sorted and unique")


def _content_id_tuple(value: object, *, field: str) -> None:
    _string_tuple(value, field=field)
    assert isinstance(value, tuple)
    for item in value:
        _validate_content_id(item, field=field)


def _validate_content_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _CONTENT_ID.fullmatch(value) is None:
        raise IdentityRecordError(f"{field} must be a content identity")
    return value


def _validate_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise IdentityRecordError(f"{field} must be a SHA-256 digest")
    return value
