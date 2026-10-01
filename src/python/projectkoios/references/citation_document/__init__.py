"""Deprecated compatibility facade for the canonical documents package."""

from __future__ import annotations

import warnings

from projectkoios.references import bibliography as _bibliography
from projectkoios.references import citations as _citations
from projectkoios.references import documents as _documents

_WARNED_DEPRECATED_EXPORTS: set[str] = set()


def __getattr__(name: str) -> object:
    if name in _documents._CITATION_DEPRECATED_EXPORTS:
        value = getattr(_citations, name)
        owner = "projectkoios.references.citations"
    elif name in _documents._BIBLIOGRAPHY_DEPRECATED_EXPORTS:
        value = getattr(_bibliography, name)
        owner = "projectkoios.references.bibliography"
    elif name in _documents.__all__:
        value = getattr(_documents, name)
        owner = "projectkoios.references.documents"
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if name not in _WARNED_DEPRECATED_EXPORTS:
        warnings.warn(
            f"projectkoios.references.citation_document.{name} is deprecated; "
            f"import {name} from {owner} instead",
            DeprecationWarning,
            stacklevel=2,
        )
        _WARNED_DEPRECATED_EXPORTS.add(name)
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_documents.__all__})


__all__ = list(_documents.__all__)
