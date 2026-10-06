# `ReferenceEvidenceArtifact`

Immutable media type, SHA-256 identity, and byte-length description for one
referenced evidence artifact, owned by
[`projectkoios.references.ingestion.evidence`](../index.md).

## VVUQ classification

Its tests are `software_verification`; the remaining VVUQ evidence classes are
not applicable.

## Software-verification evidence

`tests/test__IngestionEvidence.py` verifies exact decoding, artifact media
requirements, digest grammar, and byte bounds.
