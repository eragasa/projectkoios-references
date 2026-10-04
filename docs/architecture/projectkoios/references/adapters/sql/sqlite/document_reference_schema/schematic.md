# Document/reference schema schematic

```mermaid
classDiagram
    class ReferenceCollection {
        collection_id
        source_id
        source_revision
    }
    class ReferenceRecord {
        citekey
        bibtex_entry
    }
    class Membership {
        collection_id
        citekey
        pdf_requirement
    }
    class Document {
        sha256
        byte_size
        media_type
    }
    class Receipt {
        receipt_id
        document_sha256
        source_link
    }
    class Binding {
        binding_id
        citekey
        document_sha256
        linkage_basis
    }
    ReferenceCollection "1" --> "many" Membership
    ReferenceRecord "1" --> "many" Membership
    ReferenceRecord "1" --> "0..1" Binding
    Document "1" --> "0..1" Binding
    Document "1" --> "many" Receipt
```

Missing PDFs are not rows. They are required collection memberships for which
no reference/document binding exists.

- [Module index](index.md)
- [Implementation](implementation.md)
