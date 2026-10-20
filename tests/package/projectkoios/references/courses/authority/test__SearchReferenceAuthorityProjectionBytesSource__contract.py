"""Search authority projection bytes source port contract tests."""

from projectkoios.references.courses.authority.search_projection import (
    SearchReferenceAuthorityProjectionBytesSource,
)


def test__SearchReferenceAuthorityProjectionBytesSource__is_protocol() -> None:
    assert hasattr(SearchReferenceAuthorityProjectionBytesSource, "action")
