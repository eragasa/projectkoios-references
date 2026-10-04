from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from projectkoios.references.identity import (
    ReferenceCandidate,
    SourceBibliographyObservation,
)
from projectkoios.references.path_safety import (
    AuthorizedRoot,
    CloudPlaceholderProbe,
    RootStorageClass,
)

from ._replay import _CatalogReplayInternals
from .schema import (
    _KNOWN_LEGACY_SCHEMAS,
    _LEGACY_METADATA_KEYS,
    _LEGACY_SCHEMA_VERSIONS,
    _PUBLISHED_V2_TABLE_MAP,
    _PUBLISHED_V3_TABLE_MAP,
    _PUBLISHED_V4_TABLE_MAP,
    _SCHEMA_METADATA_KEYS,
    _TARGET_SCHEMA_STATEMENTS,
    _V1_TABLE_MAP,
    CATALOG_SCHEMA_FINGERPRINT,
    CATALOG_SCHEMA_VERSION,
    CatalogConflictError,
    CatalogMigrationRequired,
    CatalogSchemaError,
    _schema_fingerprint,
    _SchemaState,
)
from .serialization import (
    _CANDIDATE_COLUMNS,
    _OBSERVATION_COLUMNS,
    _candidate_values,
    _observation_values,
)


class _CatalogInternals(_CatalogReplayInternals):
    """Private schema, migration, transaction, and path internals."""

    path: Path
    storage_class: RootStorageClass
    placeholder_probe: CloudPlaceholderProbe | None

    @staticmethod
    def _open(path: Path) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(path, isolation_level=None)
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            return connection
        except sqlite3.DatabaseError as error:
            raise CatalogSchemaError(
                "catalog is not a readable SQLite database; preserve it and "
                "restore or migrate from a verified backup"
            ) from error

    def _inspect_schema(
        self, connection: sqlite3.Connection
    ) -> _SchemaState | None:
        try:
            objects = connection.execute(
                """
                SELECT name FROM sqlite_schema
                WHERE name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        except sqlite3.DatabaseError as error:
            raise CatalogSchemaError(
                "catalog schema cannot be inspected; preserve it and use a "
                "verified backup or explicit migration"
            ) from error
        if not objects:
            return None
        fingerprint = _schema_fingerprint(connection)
        try:
            metadata_rows = connection.execute(
                "SELECT key, value FROM catalog_metadata ORDER BY key"
            ).fetchall()
        except sqlite3.DatabaseError as error:
            raise CatalogSchemaError(
                "catalog metadata is missing or incompatible; preserve the "
                "database and use a verified backup or explicit migration"
            ) from error
        metadata = tuple((str(row[0]), str(row[1])) for row in metadata_rows)
        metadata_map = dict(metadata)
        if len(metadata_map) != len(metadata):
            raise CatalogSchemaError("catalog metadata contains duplicate keys")
        raw_version = metadata_map.get("schema_version")
        try:
            version = int(raw_version) if raw_version is not None else -1
        except ValueError as error:
            raise CatalogSchemaError(
                "catalog schema_version metadata is not an integer"
            ) from error
        if raw_version != str(version):
            raise CatalogSchemaError(
                "catalog schema_version metadata is not canonical"
            )
        if version > CATALOG_SCHEMA_VERSION:
            raise CatalogSchemaError(
                f"catalog schema version {version} is newer than supported "
                f"version {CATALOG_SCHEMA_VERSION}; use a compatible build"
            )
        if version == CATALOG_SCHEMA_VERSION:
            if frozenset(metadata_map) != _SCHEMA_METADATA_KEYS:
                raise CatalogSchemaError(
                    "current catalog metadata keys are incomplete or unexpected"
                )
            stored = metadata_map["schema_fingerprint"]
            if stored != CATALOG_SCHEMA_FINGERPRINT:
                raise CatalogSchemaError(
                    "catalog schema fingerprint metadata differs from the "
                    "supported fingerprint; preserve the database and require "
                    "an explicit migration or recovery"
                )
            if fingerprint != CATALOG_SCHEMA_FINGERPRINT:
                raise CatalogSchemaError(
                    "catalog actual schema differs from its recorded supported "
                    "schema; preserve the database and require an explicit "
                    "migration or recovery"
                )
            return _SchemaState(version, fingerprint, "current", metadata)
        if version in {1, 2, 3, 4}:
            expected_keys = (
                _LEGACY_METADATA_KEYS if version == 1 else _SCHEMA_METADATA_KEYS
            )
            if frozenset(metadata_map) != expected_keys:
                raise CatalogSchemaError(
                    f"version {version} catalog metadata is incomplete or "
                    "unexpected"
                )
            if version in {2, 3, 4} and (
                metadata_map["schema_fingerprint"] != fingerprint
            ):
                raise CatalogSchemaError(
                    f"version {version} catalog fingerprint metadata differs "
                    "from its actual schema; preserve it and require explicit "
                    "recovery"
                )
            kind = _KNOWN_LEGACY_SCHEMAS.get(fingerprint)
            if kind is None:
                raise CatalogSchemaError(
                    f"catalog claims schema version {version} but its actual "
                    "schema is unknown or altered; preserve it and require an "
                    "explicit reviewed migration"
                )
            if _LEGACY_SCHEMA_VERSIONS[kind] != version:
                raise CatalogSchemaError(
                    f"catalog claims schema version {version} but its exact "
                    f"fingerprint belongs to {kind}; preserve it and require "
                    "explicit recovery"
                )
            self._require_foreign_keys(connection)
            return _SchemaState(version, fingerprint, kind, metadata)
        raise CatalogSchemaError(
            f"catalog schema version {version} is unsupported; preserve the "
            "database and require an explicit reviewed migration"
        )

    def _require_current_schema(self, connection: sqlite3.Connection) -> None:
        state = self._inspect_schema(connection)
        if state is None:
            raise CatalogSchemaError("catalog is empty; initialize it first")
        if state.kind != "current":
            raise self._migration_required(state)
        self._require_foreign_keys(connection)
        self._validate_identity_rows(connection)
        self._validate_graph_rows(connection)
        self._validate_review_rows(connection)
        self._validate_state_projection_rows(connection)

    @staticmethod
    def _migration_required(state: _SchemaState) -> CatalogMigrationRequired:
        return CatalogMigrationRequired(
            f"recognized {state.kind} catalog ({state.fingerprint}) requires "
            f"forward migration to schema version {CATALOG_SCHEMA_VERSION}; "
            "create and verify an "
            "external backup or disposable copy, then call "
            "migrate(backup_confirmed=True)"
        )

    @staticmethod
    def _require_foreign_keys(connection: sqlite3.Connection) -> None:
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            first = tuple(violations[0])
            raise CatalogSchemaError(
                "catalog foreign-key integrity check failed; first violation "
                f"is {first!r}"
            )

    @staticmethod
    def _create_target_schema(connection: sqlite3.Connection) -> None:
        for statement in _TARGET_SCHEMA_STATEMENTS:
            connection.execute(statement)
        actual = _schema_fingerprint(connection)
        if actual != CATALOG_SCHEMA_FINGERPRINT:
            raise CatalogSchemaError(
                "created catalog schema fingerprint is not the supported "
                "fingerprint"
            )

    @staticmethod
    def _write_target_metadata(connection: sqlite3.Connection) -> None:
        connection.execute(
            "INSERT INTO catalog_metadata(key, value) VALUES (?, ?)",
            ("schema_version", str(CATALOG_SCHEMA_VERSION)),
        )
        connection.execute(
            "INSERT INTO catalog_metadata(key, value) VALUES (?, ?)",
            ("schema_fingerprint", CATALOG_SCHEMA_FINGERPRINT),
        )

    @staticmethod
    def _insert_exact(
        connection: sqlite3.Connection,
        *,
        table: str,
        columns: tuple[str, ...],
        values: tuple[object, ...],
        key_columns: tuple[str, ...],
        key_values: tuple[object, ...],
        label: str,
        conflict_type: type[CatalogConflictError] = CatalogConflictError,
    ) -> bool:
        select_columns = ", ".join(f'"{item}"' for item in columns)
        where = " AND ".join(f'"{item}" = ?' for item in key_columns)
        existing = connection.execute(
            f'SELECT {select_columns} FROM "{table}" WHERE {where}',  # noqa: S608
            key_values,
        ).fetchone()
        if existing is not None:
            if tuple(existing) == values:
                return False
            raise conflict_type(f"{label} conflicts with existing evidence")
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(f'"{item}"' for item in columns)
        connection.execute(
            f'INSERT INTO "{table}" ({column_sql}) '  # noqa: S608
            f"VALUES ({placeholders})",
            values,
        )
        return True

    @staticmethod
    def _snapshot_table(
        connection: sqlite3.Connection, table: str
    ) -> tuple[tuple[str, ...], tuple[tuple[object, ...], ...]]:
        columns = tuple(
            str(row[1])
            for row in connection.execute(
                f'PRAGMA table_info("{table}")'  # noqa: S608
            ).fetchall()
        )
        column_sql = ", ".join(f'"{item}"' for item in columns)
        rows = tuple(
            tuple(row)
            for row in connection.execute(
                f'SELECT {column_sql} FROM "{table}" ORDER BY rowid'  # noqa: S608
            ).fetchall()
        )
        return columns, rows

    def _snapshot_legacy(
        self, connection: sqlite3.Connection, state: _SchemaState
    ) -> dict[str, Any]:
        table_map: tuple[tuple[str, str], ...]
        if state.kind == "published-v4":
            table_map = _PUBLISHED_V4_TABLE_MAP
        elif state.kind == "published-v3":
            table_map = _PUBLISHED_V3_TABLE_MAP
        elif state.kind == "published-v2":
            table_map = _PUBLISHED_V2_TABLE_MAP
        else:
            table_map = _V1_TABLE_MAP
        snapshot: dict[str, Any] = {
            "table_map": table_map,
            **{
                source: self._snapshot_table(connection, source)
                for source, _ in table_map
            },
        }
        if state.kind == "identity-v1":
            try:
                observations = tuple(
                    SourceBibliographyObservation.from_json(str(row[3]))
                    for row in connection.execute(
                        """
                        SELECT observation_id, authority_kind, observed_citekey,
                               observation_json
                        FROM source_bibliography_observations
                        ORDER BY observation_id
                        """
                    ).fetchall()
                )
            except ValueError as error:
                raise CatalogSchemaError(
                    "legacy observation canonical JSON is invalid"
                ) from error
            old_observation_rows = connection.execute(
                """
                SELECT observation_id, authority_kind, observed_citekey,
                       observation_json
                FROM source_bibliography_observations
                ORDER BY observation_id
                """
            ).fetchall()
            for row, observation in zip(
                old_observation_rows, observations, strict=True
            ):
                observation_expected = (
                    observation.observation_id,
                    observation.authority_kind,
                    observation.observed_citekey,
                    observation.to_json(),
                )
                if tuple(row) != observation_expected:
                    raise CatalogSchemaError(
                        "legacy observation scalar columns differ from "
                        "canonical JSON"
                    )
            try:
                candidates = tuple(
                    ReferenceCandidate.from_json(str(row[5]))
                    for row in connection.execute(
                        """
                        SELECT candidate_id, authority_kind, lifecycle_status,
                               proposed_citekey, citekey_status, candidate_json
                        FROM reference_candidates
                        ORDER BY candidate_id
                        """
                    ).fetchall()
                )
            except ValueError as error:
                raise CatalogSchemaError(
                    "legacy candidate canonical JSON is invalid"
                ) from error
            old_candidate_rows = connection.execute(
                """
                SELECT candidate_id, authority_kind, lifecycle_status,
                       proposed_citekey, citekey_status, candidate_json
                FROM reference_candidates
                ORDER BY candidate_id
                """
            ).fetchall()
            for row, candidate in zip(
                old_candidate_rows, candidates, strict=True
            ):
                candidate_expected = (
                    candidate.candidate_id,
                    candidate.authority_kind,
                    candidate.lifecycle_status,
                    candidate.proposed_citekey,
                    candidate.citekey_status,
                    candidate.to_json(),
                )
                if tuple(row) != candidate_expected:
                    raise CatalogSchemaError(
                        "legacy candidate scalar columns differ from "
                        "canonical JSON"
                    )
            links = self._snapshot_table(
                connection, "candidate_source_observations"
            )
            assets = self._snapshot_table(connection, "candidate_source_assets")
            observation_ids = {item.observation_id for item in observations}
            candidate_ids = {item.candidate_id for item in candidates}
            linked_by_candidate: dict[str, list[str]] = {
                item: [] for item in candidate_ids
            }
            for candidate_id, observation_id in links[1]:
                candidate_text = str(candidate_id)
                observation_text = str(observation_id)
                if (
                    candidate_text not in candidate_ids
                    or observation_text not in observation_ids
                ):
                    raise CatalogSchemaError(
                        "legacy candidate-source link has a missing identity"
                    )
                linked_by_candidate[candidate_text].append(observation_text)
            for candidate in candidates:
                linked = tuple(
                    sorted(linked_by_candidate[candidate.candidate_id])
                )
                if linked != candidate.source_observation_ids:
                    raise CatalogSchemaError(
                        "legacy candidate-source links differ from canonical "
                        "JSON"
                    )
            candidate_by_id = {
                candidate.candidate_id: candidate for candidate in candidates
            }
            for row in assets[1]:
                asset = self._source_asset_from_row(
                    row, label="legacy candidate source asset"
                )
                self._require_asset_candidate_match(
                    asset,
                    candidate_by_id,
                    label="legacy candidate source asset",
                )
            snapshot.update(
                {
                    "observations": observations,
                    "candidates": candidates,
                    "candidate_source_observations": links,
                    "candidate_source_assets": assets,
                }
            )
        elif state.kind in {
            "published-v2",
            "published-v3",
            "published-v4",
        }:
            self._validate_identity_rows(connection)
            if state.kind in {"published-v3", "published-v4"}:
                self._validate_graph_rows(connection)
            if state.kind == "published-v4":
                self._validate_review_rows(connection)
            observations = self._read_observations(connection)
            observation_ids = {
                observation.observation_id for observation in observations
            }
            candidates = self._read_candidates(connection, observation_ids)
            snapshot.update(
                {
                    "observations": observations,
                    "candidates": candidates,
                    "candidate_source_observations": self._snapshot_table(
                        connection,
                        "candidate_source_observations",
                    ),
                    "candidate_source_assets": self._snapshot_table(
                        connection,
                        "candidate_source_assets",
                    ),
                }
            )
        else:
            snapshot.update(
                {
                    "observations": (),
                    "candidates": (),
                    "candidate_source_observations": (
                        ("candidate_id", "observation_id"),
                        (),
                    ),
                    "candidate_source_assets": (
                        (
                            "candidate_id",
                            "proposed_citekey",
                            "identity_status",
                            "citekey_status",
                            "sha256",
                            "byte_size",
                            "root_alias",
                            "relative_path",
                            "rights_status",
                            "asset_status",
                        ),
                        (),
                    ),
                }
            )
        return snapshot

    def _restore_snapshot(
        self,
        connection: sqlite3.Connection,
        snapshot: dict[str, Any],
    ) -> None:
        for observation in snapshot["observations"]:
            self._insert_exact(
                connection,
                table="source_bibliography_observations",
                columns=_OBSERVATION_COLUMNS,
                values=_observation_values(observation),
                key_columns=("observation_id",),
                key_values=(observation.observation_id,),
                label="migrated observation",
            )
        for candidate in snapshot["candidates"]:
            self._insert_exact(
                connection,
                table="reference_candidates",
                columns=_CANDIDATE_COLUMNS,
                values=_candidate_values(candidate),
                key_columns=("candidate_id",),
                key_values=(candidate.candidate_id,),
                label="migrated candidate",
            )
        self._restore_table(
            connection,
            "candidate_source_observations",
            snapshot["candidate_source_observations"],
        )
        self._restore_table(
            connection,
            "candidate_source_assets",
            snapshot["candidate_source_assets"],
        )
        for source, target in snapshot["table_map"]:
            self._restore_table(connection, target, snapshot[source])
        self._validate_identity_rows(connection)
        self._validate_graph_rows(connection)
        self._validate_review_rows(connection)
        self._validate_state_projection_rows(connection)

    @staticmethod
    def _restore_table(
        connection: sqlite3.Connection,
        table: str,
        snapshot: tuple[tuple[str, ...], tuple[tuple[object, ...], ...]],
    ) -> None:
        columns, rows = snapshot
        if not rows:
            return
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(f'"{item}"' for item in columns)
        connection.executemany(
            f'INSERT INTO "{table}" ({column_sql}) '  # noqa: S608
            f"VALUES ({placeholders})",
            rows,
        )

    def _migration_checkpoint(self, step: str) -> None:
        """Test seam proving DDL/data rollback; production is a no-op."""
        del step

    def _safe_path(self, *, create_parent: bool) -> Path:
        root = (
            AuthorizedRoot.create(
                self.path.parent,
                label="reference catalog parent",
                root_alias="reference-catalog-parent",
                storage_class=self.storage_class,
                placeholder_probe=self.placeholder_probe,
            )
            if create_parent
            else AuthorizedRoot.existing(
                self.path.parent,
                label="reference catalog parent",
                root_alias="reference-catalog-parent",
                storage_class=self.storage_class,
                placeholder_probe=self.placeholder_probe,
            )
        )
        state = root.state(self.path.name)
        if state == "regular":
            root.require_readable_file(self.path.name)
        if state == "directory":
            raise ValueError("reference catalog path is a directory")
        if state == "missing" and not create_parent:
            raise CatalogSchemaError(
                "catalog does not exist; initialize a new catalog explicitly"
            )
        return root.child_path(self.path.name)
