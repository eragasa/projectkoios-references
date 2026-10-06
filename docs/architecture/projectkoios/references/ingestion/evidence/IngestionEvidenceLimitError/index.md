# `IngestionEvidenceLimitError`

Limit failure owned by [`projectkoios.references.ingestion.evidence`](../index.md).
It is raised before untrusted evidence exceeds deterministic byte, item,
nesting, string, lineage, layout, or layer bounds.

## VVUQ classification

`software_verification` applies; the three numerical/scientific VVUQ evidence
classes do not apply.

## Software-verification evidence

`tests/test__IngestionEvidence.py` verifies byte and structural bound failures.
