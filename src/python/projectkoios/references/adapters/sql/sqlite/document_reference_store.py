"""SQLite persistence for the small document/reference model."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import final

from projectkoios.references.adapters.sql.sqlite import (
    document_reference_schema,
)
from projectkoios.references.document_reference.base import (
    AbstractDocumentReferenceDataObject,
)
from projectkoios.references.document_reference.bibliography.metadata.errors import (  # noqa: E501
    BibliographyMetadataError,
)
from projectkoios.references.document_reference.bibliography.metadata.reader import (  # noqa: E501
    BibliographyMetadataReader,
)
from projectkoios.references.document_reference.bibliography.record import (
    ReferenceRecord,
)
from projectkoios.references.document_reference.bindings.binding import (
    ReferenceDocumentBinding,
)
from projectkoios.references.document_reference.bindings.disposition import (
    BindingDisposition,
)
from projectkoios.references.document_reference.bindings.errors import (
    ReferenceDocumentBindingConflict,
)
from projectkoios.references.document_reference.bindings.result import (
    BindPdfToReferenceResult,
)
from projectkoios.references.document_reference.bindings.selection import (
    ReferenceDocumentBindingSelection,
)
from projectkoios.references.document_reference.collections.collection import (
    ReferenceCollection,
)
from projectkoios.references.document_reference.collections.errors import (
    UnknownCollection,
    UnknownReference,
)
from projectkoios.references.document_reference.collections.membership import (
    ReferenceCollectionMembership,
)
from projectkoios.references.document_reference.collections.missing.item import (  # noqa: E501
    MissingPdfReference,
)
from projectkoios.references.document_reference.collections.missing.result import (  # noqa: E501
    ListMissingPdfReferencesResult,
)
from projectkoios.references.document_reference.collections.pdf_requirement import (  # noqa: E501
    PdfRequirement,
)
from projectkoios.references.document_reference.constants import (
    MAX_COLLECTION_MEMBERS,
)
from projectkoios.references.document_reference.documents.errors import (
    DocumentContentConflict,
    UnknownDocument,
)
from projectkoios.references.document_reference.documents.receipt.effect import (  # noqa: E501
    ReceiptRecordEffect,
)
from projectkoios.references.document_reference.documents.stored_pdf import (
    StoredPdfObject,
)
from projectkoios.references.document_reference.errors import (
    DocumentReferenceStoreError,
)
from projectkoios.references.path_safety.preflight import RootStorageClass
from projectkoios.references.path_safety.root import AuthorizedRoot

_DATABASE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\.sqlite3")


@final
class SqliteDocumentReferenceStore:
    """Persist document/reference rows below one authorized local root."""

    __slots__ = (
        "_database_name",
        "_database_path",
        "_database_root",
        "_metadata_reader",
    )

    def __init__(
        self,
        *,
        database_root: AuthorizedRoot,
        database_name: str,
        metadata_reader: BibliographyMetadataReader,
    ) -> None:
        if (
            type(database_name) is not str
            or _DATABASE_NAME.fullmatch(database_name) is None
        ):
            raise ValueError(
                "database_name must be a bounded .sqlite3 leaf name"
            )
        if (
            database_root.preflight_evidence.storage_class
            is not RootStorageClass.LOCAL
        ):
            raise ValueError("document/reference database root must be local")
        self._database_root = database_root
        self._database_name = database_name
        self._database_path = database_root.child_path(database_name)
        self._metadata_reader = metadata_reader

    @property
    def database_path(self) -> Path:
        """Return the configured database path for operator diagnostics."""
        return self._database_path

    def initialize(self) -> None:
        """Create or verify the parallel schema without importing any rows."""
        try:
            state = self._database_root.state(self._database_name)
            if state == "directory":
                raise DocumentReferenceStoreError(
                    "document/reference database path is a directory"
                )
            if state == "missing":
                try:
                    self._database_root.write_bytes(
                        self._database_name,
                        b"",
                        replace=False,
                    )
                except FileExistsError:
                    pass
            connection = self._open_unverified()
            try:
                objects = connection.execute(
                    "SELECT name FROM sqlite_schema "
                    "WHERE name NOT LIKE 'sqlite_%'"
                ).fetchall()
                if objects:
                    document_reference_schema.DocumentReferenceSchema.require_supported(
                        connection
                    )
                else:
                    document_reference_schema.DocumentReferenceSchema.initialize(
                        connection
                    )
            finally:
                connection.close()
        except DocumentReferenceStoreError:
            raise
        except (OSError, sqlite3.DatabaseError, ValueError) as error:
            raise DocumentReferenceStoreError(
                "document/reference database initialization failed"
            ) from error

    def record_reference(self, *, reference: ReferenceRecord) -> None:
        """Insert an exact reference or accept an exact idempotent replay."""
        self._missing_pdf_reference(
            citekey=reference.citekey,
            bibtex_entry=reference.bibtex_entry,
        )
        connection = self._open()
        try:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT bibtex_entry FROM reference_records "
                    "WHERE citekey = ?",
                    (reference.citekey,),
                ).fetchone()
                if existing is None:
                    connection.execute(
                        "INSERT INTO reference_records(citekey, bibtex_entry) "
                        "VALUES (?, ?)",
                        (reference.citekey, reference.bibtex_entry),
                    )
                elif existing != (reference.bibtex_entry,):
                    raise DocumentReferenceStoreError(
                        "citekey already has different BibTeX content"
                    )
        except DocumentReferenceStoreError:
            raise
        except sqlite3.DatabaseError as error:
            raise DocumentReferenceStoreError(
                "reference record could not be stored"
            ) from error
        finally:
            connection.close()

    def record_collection(self, *, collection: ReferenceCollection) -> None:
        """Insert exact collection provenance or accept an exact replay."""
        connection = self._open()
        try:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT source_id, source_revision "
                    "FROM reference_collections WHERE collection_id = ?",
                    (collection.collection_id,),
                ).fetchone()
                expected = (collection.source_id, collection.source_revision)
                if existing is None:
                    connection.execute(
                        "INSERT INTO reference_collections("
                        "collection_id, source_id, source_revision) "
                        "VALUES (?, ?, ?)",
                        (
                            collection.collection_id,
                            collection.source_id,
                            collection.source_revision,
                        ),
                    )
                elif existing != expected:
                    raise DocumentReferenceStoreError(
                        "collection already has different provenance"
                    )
        except DocumentReferenceStoreError:
            raise
        except sqlite3.DatabaseError as error:
            raise DocumentReferenceStoreError(
                "reference collection could not be stored"
            ) from error
        finally:
            connection.close()

    def record_membership(
        self, *, membership: ReferenceCollectionMembership
    ) -> None:
        """Insert one exact collection membership without replacement."""
        connection = self._open()
        try:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                if (
                    connection.execute(
                        "SELECT 1 FROM reference_collections "
                        "WHERE collection_id = ?",
                        (membership.collection_id,),
                    ).fetchone()
                    is None
                ):
                    raise UnknownCollection("unknown reference collection")
                if (
                    connection.execute(
                        "SELECT 1 FROM reference_records WHERE citekey = ?",
                        (membership.citekey,),
                    ).fetchone()
                    is None
                ):
                    raise UnknownReference("unknown reference citekey")
                existing = connection.execute(
                    "SELECT pdf_requirement "
                    "FROM reference_collection_memberships "
                    "WHERE collection_id = ? AND citekey = ?",
                    (membership.collection_id, membership.citekey),
                ).fetchone()
                if existing is None:
                    count = connection.execute(
                        "SELECT COUNT(*) "
                        "FROM reference_collection_memberships "
                        "WHERE collection_id = ?",
                        (membership.collection_id,),
                    ).fetchone()
                    if count is None or int(count[0]) >= MAX_COLLECTION_MEMBERS:
                        raise DocumentReferenceStoreError(
                            "collection membership cap reached"
                        )
                    connection.execute(
                        "INSERT INTO reference_collection_memberships("
                        "collection_id, citekey, pdf_requirement) "
                        "VALUES (?, ?, ?)",
                        (
                            membership.collection_id,
                            membership.citekey,
                            membership.pdf_requirement.value,
                        ),
                    )
                elif existing != (membership.pdf_requirement.value,):
                    raise DocumentReferenceStoreError(
                        "collection member already has a different PDF "
                        "requirement"
                    )
        except UnknownCollection, UnknownReference, DocumentReferenceStoreError:
            raise
        except sqlite3.DatabaseError as error:
            raise DocumentReferenceStoreError(
                "reference collection membership could not be stored"
            ) from error
        finally:
            connection.close()

    def record_pdf_receipt(
        self,
        *,
        document: StoredPdfObject,
        source_link: str | None,
    ) -> ReceiptRecordEffect:
        """Atomically record a document and one immutable source observation."""
        AbstractDocumentReferenceDataObject._validate_source_link(source_link)
        receipt_id = self.receipt_id(
            document_sha256=document.sha256,
            source_link=source_link,
        )
        connection = self._open()
        try:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                existing_document = connection.execute(
                    "SELECT byte_size, media_type FROM documents "
                    "WHERE sha256 = ?",
                    (document.sha256,),
                ).fetchone()
                document_created = existing_document is None
                if document_created:
                    connection.execute(
                        "INSERT INTO documents(sha256, byte_size, media_type) "
                        "VALUES (?, ?, 'application/pdf')",
                        (document.sha256, document.byte_size),
                    )
                elif existing_document != (
                    document.byte_size,
                    "application/pdf",
                ):
                    raise DocumentContentConflict(
                        "document digest already has different recorded content"
                    )
                existing_receipt = connection.execute(
                    "SELECT document_sha256, source_link "
                    "FROM document_receipts WHERE receipt_id = ?",
                    (receipt_id,),
                ).fetchone()
                expected_receipt = (document.sha256, source_link)
                receipt_created = existing_receipt is None
                if receipt_created:
                    connection.execute(
                        "INSERT INTO document_receipts("
                        "receipt_id, document_sha256, source_link) "
                        "VALUES (?, ?, ?)",
                        (receipt_id, document.sha256, source_link),
                    )
                elif existing_receipt != expected_receipt:
                    raise DocumentContentConflict(
                        "receipt identity conflicts with existing source "
                        "evidence"
                    )
            return ReceiptRecordEffect(
                receipt_id=receipt_id,
                document_created=document_created,
                receipt_created=receipt_created,
            )
        except DocumentContentConflict, DocumentReferenceStoreError:
            raise
        except sqlite3.DatabaseError as error:
            raise DocumentReferenceStoreError(
                "PDF receipt could not be stored"
            ) from error
        finally:
            connection.close()

    def list_missing_pdf_references(
        self, *, collection_id: str
    ) -> ListMissingPdfReferencesResult:
        """Derive missing rows; never persist a separate missing status."""
        AbstractDocumentReferenceDataObject._validate_identifier(
            collection_id,
            field="collection_id",
        )
        connection = self._open()
        try:
            collection = connection.execute(
                "SELECT source_id, source_revision FROM reference_collections "
                "WHERE collection_id = ?",
                (collection_id,),
            ).fetchone()
            if collection is None:
                raise UnknownCollection("unknown reference collection")
            counts = connection.execute(
                "SELECT "
                "SUM(CASE WHEN m.pdf_requirement = 'required' "
                "THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN m.pdf_requirement = 'required' "
                "AND b.citekey IS NOT NULL THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN m.pdf_requirement = 'not-applicable' "
                "THEN 1 ELSE 0 END) "
                "FROM reference_collection_memberships AS m "
                "LEFT JOIN reference_document_bindings AS b "
                "ON b.citekey = m.citekey WHERE m.collection_id = ?",
                (collection_id,),
            ).fetchone()
            rows = connection.execute(
                "SELECT m.citekey, r.bibtex_entry "
                "FROM reference_collection_memberships AS m "
                "JOIN reference_records AS r ON r.citekey = m.citekey "
                "LEFT JOIN reference_document_bindings AS b "
                "ON b.citekey = m.citekey "
                "WHERE m.collection_id = ? "
                "AND m.pdf_requirement = 'required' "
                "AND b.citekey IS NULL ORDER BY m.citekey "
                "LIMIT ?",
                (collection_id, MAX_COLLECTION_MEMBERS + 1),
            ).fetchall()
            if len(rows) > MAX_COLLECTION_MEMBERS:
                raise DocumentReferenceStoreError(
                    "derived missing list exceeds the collection cap"
                )
            required, bound, not_applicable = (
                int(value or 0) for value in (counts or (0, 0, 0))
            )
            try:
                missing = tuple(
                    self._missing_pdf_reference(
                        citekey=str(row[0]),
                        bibtex_entry=str(row[1]),
                    )
                    for row in rows
                )
            except BibliographyMetadataError:
                raise
            except ValueError as error:
                raise DocumentReferenceStoreError(
                    "stored reference metadata is invalid"
                ) from error
            return ListMissingPdfReferencesResult(
                collection_id=collection_id,
                source_id=str(collection[0]),
                source_revision=str(collection[1]),
                required_count=required,
                bound_count=bound,
                not_applicable_count=not_applicable,
                missing=missing,
            )
        except (
            BibliographyMetadataError,
            UnknownCollection,
            DocumentReferenceStoreError,
        ):
            raise
        except sqlite3.DatabaseError as error:
            raise DocumentReferenceStoreError(
                "missing-PDF list could not be derived"
            ) from error
        finally:
            connection.close()

    def bind_reference_document(
        self, *, selection: ReferenceDocumentBindingSelection
    ) -> BindPdfToReferenceResult:
        """Atomically create one binding, accept an exact retry, or conflict."""
        binding = self.binding_for(selection=selection)
        connection = self._open()
        try:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                if (
                    connection.execute(
                        "SELECT 1 FROM reference_collections "
                        "WHERE collection_id = ?",
                        (selection.collection_id,),
                    ).fetchone()
                    is None
                ):
                    raise UnknownCollection("unknown reference collection")
                membership = connection.execute(
                    "SELECT pdf_requirement "
                    "FROM reference_collection_memberships "
                    "WHERE collection_id = ? AND citekey = ?",
                    (selection.collection_id, selection.citekey),
                ).fetchone()
                if membership is None:
                    raise UnknownReference(
                        "citekey is not a member of the selected collection"
                    )
                if membership != (PdfRequirement.REQUIRED.value,):
                    raise ReferenceDocumentBindingConflict(
                        "selected collection member does not require a PDF"
                    )
                if (
                    connection.execute(
                        "SELECT 1 FROM documents WHERE sha256 = ?",
                        (selection.document_sha256,),
                    ).fetchone()
                    is None
                ):
                    raise UnknownDocument("unknown PDF document digest")
                existing = connection.execute(
                    "SELECT binding_id, citekey, document_sha256, "
                    "linkage_basis "
                    "FROM reference_document_bindings "
                    "WHERE citekey = ? OR document_sha256 = ?",
                    (selection.citekey, selection.document_sha256),
                ).fetchall()
                expected = (
                    binding.binding_id,
                    binding.citekey,
                    binding.document_sha256,
                    binding.linkage_basis,
                )
                if not existing:
                    connection.execute(
                        "INSERT INTO reference_document_bindings("
                        "binding_id, citekey, document_sha256, linkage_basis) "
                        "VALUES (?, ?, ?, ?)",
                        expected,
                    )
                    disposition = BindingDisposition.BOUND
                elif existing == [expected]:
                    disposition = BindingDisposition.ALREADY_BOUND
                else:
                    raise ReferenceDocumentBindingConflict(
                        "citekey or document already has a different binding"
                    )
            return BindPdfToReferenceResult(
                binding=binding,
                disposition=disposition,
            )
        except (
            UnknownCollection,
            UnknownReference,
            UnknownDocument,
            ReferenceDocumentBindingConflict,
            DocumentReferenceStoreError,
        ):
            raise
        except sqlite3.DatabaseError as error:
            raise DocumentReferenceStoreError(
                "reference/document binding could not be stored"
            ) from error
        finally:
            connection.close()

    @staticmethod
    def receipt_id(*, document_sha256: str, source_link: str | None) -> str:
        """Derive an immutable receipt ID from content and source evidence."""
        payload = json.dumps(
            [document_sha256, source_link],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
        return f"document-receipt:sha256:{hashlib.sha256(payload).hexdigest()}"

    @staticmethod
    def binding_for(
        *, selection: ReferenceDocumentBindingSelection
    ) -> ReferenceDocumentBinding:
        """Derive the neutral binding and its stable identity."""
        payload = json.dumps(
            [
                selection.citekey,
                selection.document_sha256,
                selection.linkage_basis.value,
            ],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
        binding_id = (
            "reference-document-binding:sha256:"
            f"{hashlib.sha256(payload).hexdigest()}"
        )
        return ReferenceDocumentBinding(
            binding_id=binding_id,
            citekey=selection.citekey,
            document_sha256=selection.document_sha256,
            linkage_basis=selection.linkage_basis,
        )

    def _open_unverified(self) -> sqlite3.Connection:
        self._database_root.require_readable_file(self._database_name)
        connection = sqlite3.connect(
            f"{self._database_path.as_uri()}?mode=rw",
            isolation_level=None,
            timeout=5.0,
            uri=True,
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _open(self) -> sqlite3.Connection:
        try:
            connection = self._open_unverified()
            document_reference_schema.DocumentReferenceSchema.require_supported(
                connection,
                check_integrity=False,
            )
            return connection
        except DocumentReferenceStoreError:
            raise
        except (OSError, sqlite3.DatabaseError, ValueError) as error:
            try:
                connection.close()
            except UnboundLocalError:
                pass
            raise DocumentReferenceStoreError(
                "document/reference database is unavailable or incompatible"
            ) from error

    def _missing_pdf_reference(
        self,
        *,
        citekey: str,
        bibtex_entry: str,
    ) -> MissingPdfReference:
        metadata = self._metadata_reader.read(
            citekey=citekey,
            bibtex_entry=bibtex_entry,
        )
        return MissingPdfReference(
            citekey=metadata.citekey,
            entry_type=metadata.entry_type,
            title=metadata.title,
            authors=metadata.authors,
            year=metadata.year,
        )
