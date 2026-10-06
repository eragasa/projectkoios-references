# `ReferenceEvidenceRecord`

Immutable aggregate for one canonical ingestion-reference-evidence record. Its
`to_bytes` operation reproduces the canonical producer representation.

## VVUQ classification

Its tests are `software_verification`; the record does not itself establish
numerical verification, scientific validation, or uncertainty quantification.

## Software-verification evidence

`tests/test__IngestionEvidence.py` verifies exact fixture identity, stable record
ID, canonical serialization, and byte-for-byte replay.
