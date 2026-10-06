# `IngestionEvidenceVerificationError`

Verification failure owned by
[`projectkoios.references.ingestion.evidence`](../index.md) for evidence that
cannot be bound to the declared managed-PDF identity or violates semantic
contract requirements.

## VVUQ classification

This is `software_verification`, not numerical verification, scientific
validation, or uncertainty quantification.

## Software-verification evidence

`tests/test__IngestionEvidence.py` verifies identity mismatch, duplicate,
missing-managed-PDF, and semantic contract failures.
