"""Shared document/reference failures."""


class DocumentReferenceError(RuntimeError):
    """Base failure for document/reference operations."""


class DocumentReferenceStoreError(DocumentReferenceError):
    """The durable store could not complete an operation safely."""
