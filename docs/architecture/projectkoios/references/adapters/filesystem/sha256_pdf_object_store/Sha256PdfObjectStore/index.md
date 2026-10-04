# `Sha256PdfObjectStore`

Bounded content-addressed PDF receiver using one explicit authorized local-root
capability. It validates and deduplicates bytes but does not create a citekey
binding or accept bibliographic metadata.

Evidence: [object-store implementation](../implementation.md) and [focused tests](../../../../../../../../tests/test__DocumentReferenceOperations.py).
