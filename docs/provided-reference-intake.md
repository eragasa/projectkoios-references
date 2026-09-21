# Provided-reference intake

Status: extracted candidate.

`ProvidedReferenceIntakeStore` owns the private receipt boundary for a PDF
supplied during claim review. It:

- accepts PDF bytes up to 100 MB;
- computes a content identity and an immutable metadata-sensitive receipt;
- publishes objects and records atomically with private permissions;
- rejects symlinked storage locations;
- deduplicates identical receipts without overwriting records; and
- records ingestion separately as `INGESTED_AUTOMATED_UNREVIEWED`.

Receiving a PDF does not ingest it, admit it to retrieval, verify its
bibliographic or scientific content, accept a claim, authorize publication, or
record human review. An ingestion disposition binds the receipt to the matching
content-derived source identity, affected claims, and a review generation. The
API validates that a submitted claim belongs to the active review before it
calls this owner service.
