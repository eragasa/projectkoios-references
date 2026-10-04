# `ManagedPdfScanRequest`

Immutable bounded request for scanning managed PDFs and optional source-discovery evidence.

It is owned by `loading.py` under the canonical
`projectkoios.references.collections.reconciliation` package. Requests and
results are immutable exact-runtime-type contracts; actionizers expose only the
public `action` operation and reject subtype substitution.

Evidence: [implementation](../implementation.md).
