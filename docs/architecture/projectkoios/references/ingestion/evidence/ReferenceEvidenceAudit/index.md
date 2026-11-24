# `ReferenceEvidenceAudit`

Immutable derivation-audit evidence, including artifact identity, scope,
processor identity, audited lineage, layer counts, and findings.

## VVUQ classification

Its tests are `software_verification`; a recorded producer audit is not
independent scientific validation or uncertainty quantification.

## Software-verification evidence

`tests/test__IngestionEvidence.py` verifies passing status, lineage completeness,
layer coverage, and rejection of false independent-revalidation claims.
