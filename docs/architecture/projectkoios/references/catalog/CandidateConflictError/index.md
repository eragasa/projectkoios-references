# `CandidateConflictError`

Specialized `CatalogConflictError` for a candidate identity whose stored row
differs from the incoming canonical candidate evidence. The conflict fails the
surrounding transaction rather than replacing history.

Evidence: [catalog implementation](../implementation.md) and
[`test__ReferenceCatalog.py`](../../../../../../tests/test__ReferenceCatalog.py).
