# `ReferenceEvidenceSource`

Immutable identity of the producer's source PDF, including blob identity,
hash algorithm, content digest, byte length, and media type.

## VVUQ classification

Its tests are `software_verification`; no numerical, scientific-validation, or
uncertainty-quantification claim is made.

## Software-verification evidence

`tests/test__IngestionEvidence.py` verifies exact source identity decoding and
binding to the managed PDF.
