# `IngestionEvidenceError`

Base value error owned by [`projectkoios.references.ingestion.evidence`](../index.md)
for strict ingestion-evidence consumption. Its subclasses preserve limit,
parse, and verification failure ownership.

## VVUQ classification

`software_verification` applies; `numerical_verification`,
`scientific_validation`, and `uncertainty_quantification` do not apply.

## Software-verification evidence

`tests/test__IngestionEvidence.py` verifies the operation-specific error
hierarchy through malformed, oversized, and identity-mismatched evidence.
