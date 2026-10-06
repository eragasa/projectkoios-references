# `IngestionEvidenceParseError`

Parse failure owned by [`projectkoios.references.ingestion.evidence`](../index.md)
for malformed, noncanonical, unsupported, or replay-divergent producer bytes.

## VVUQ classification

`software_verification` applies; `numerical_verification`,
`scientific_validation`, and `uncertainty_quantification` do not apply.

## Software-verification evidence

`tests/test__IngestionEvidence.py` verifies duplicate fields, canonical form,
contract compatibility, record identity, and exact replay failures.
