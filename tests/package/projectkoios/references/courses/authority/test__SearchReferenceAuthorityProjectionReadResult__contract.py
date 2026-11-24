"""Search authority projection read result contract tests."""

from projectkoios.base import DataObjectActionResult
from projectkoios.references.courses.authority.search_projection import (
    SearchReferenceAuthorityProjectionReadResult,
)


def test__SearchReferenceAuthorityProjectionReadResult__is_action_result() -> (
    None
):
    assert issubclass(
        SearchReferenceAuthorityProjectionReadResult,
        DataObjectActionResult,
    )
