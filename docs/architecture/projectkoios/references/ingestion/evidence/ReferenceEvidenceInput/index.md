# `ReferenceEvidenceInput`

Immutable explicit binding request containing citekey, evidence path, storage
class, and optional bound placeholder probe or root-binding probe factory.

## VVUQ classification

Its tests are `software_verification`; other VVUQ evidence classes do not
apply.

## Software-verification evidence

`tests/package/projectkoios/references/ingestion/evidence/test__ReferenceEvidencePathConfinement.py`
verifies citekey rejection, fail-closed symlink handling, and typed macOS probe
factory binding. The main ingestion evidence tests verify explicit storage-class
binding.
