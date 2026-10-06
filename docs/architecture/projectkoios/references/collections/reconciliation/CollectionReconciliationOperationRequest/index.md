# `CollectionReconciliationOperationRequest`

Immutable runtime-neutral request binding every explicit path capability,
storage class, collection/source identity, optional evidence artifact,
manuscript scan declaration, and source-bound ingestion-evidence input needed by
one complete collection reconciliation.

Optional path and storage-class capabilities are paired. Manuscript root,
storage class, and scan mode are all-or-none; build-graph mode additionally
requires an entrypoint. Reference-evidence inputs are exact typed values,
unique by citekey, and normalized into deterministic citekey order.

Paths remain runtime capabilities. Reconciliation outputs retain privacy-reduced
logical names and content evidence rather than absolute private roots. The
request grants no identity, rights, review, ingestion, scientific, manuscript,
Search, or publication authority.

Evidence: [implementation](../implementation.md).
