# `AssetApplicationError`

Expected domain rejection for an incomplete or conflicting application
selection, including unmatched authorization selectors and missing unique root
preflight evidence. It is a `ValueError` and does not represent scheduler,
retry, or Workflow state.

Authority, path-safety, catalog, schema, I/O-limit, and filesystem failures
retain their existing owner-specific exception types.

Evidence: [implementation](../implementation.md).
