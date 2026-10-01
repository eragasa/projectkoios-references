"""Deprecated constants from ``projectkoios.references.documents``."""

import warnings

from projectkoios.references.documents._contract import *  # noqa: F403
from projectkoios.references.documents._contract import __all__ as __all__

warnings.warn(
    "projectkoios.references.citation_document._contract is deprecated; "
    "import from projectkoios.references.documents._contract instead",
    DeprecationWarning,
    stacklevel=2,
)
