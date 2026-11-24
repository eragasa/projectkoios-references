"""Path-free Search authority projection read error tests."""

from projectkoios.references.courses.authority.search_projection import (
    SearchReferenceAuthorityProjectionReadError,
)


def test__projection_read_error__is_deterministic_and_path_free() -> None:
    error = SearchReferenceAuthorityProjectionReadError()

    assert isinstance(error, RuntimeError)
    assert error.code == "search-reference-authority-projection-unavailable"
    assert error.args == (
        "Search reference authority projection is unavailable",
    )
    assert vars(error) == {}
