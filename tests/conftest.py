"""Shared pytest fixtures for repository-owned test evidence."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def ingestion_reference_evidence_fixture(
    pytestconfig: pytest.Config,
) -> Path:
    """Return the canonical sanitized ingestion-evidence fixture."""
    fixture = (
        pytestconfig.rootpath
        / "tests"
        / "fixtures"
        / "ingestion-reference-evidence"
        / "complete.json"
    )
    if not fixture.is_file():
        raise FileNotFoundError(fixture)
    return fixture
