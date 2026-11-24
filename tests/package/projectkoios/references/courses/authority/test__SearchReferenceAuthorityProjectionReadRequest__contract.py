"""Search authority projection read request contract tests."""

import pytest
from projectkoios.base import DataObjectActionRequest
from projectkoios.references.courses.authority.errors import (
    CourseReferenceAuthorityError,
)
from projectkoios.references.courses.authority.search_projection import (
    SearchReferenceAuthorityProjectionReadRequest,
)


def test__projection_read_request__is_action_request() -> None:
    assert issubclass(
        SearchReferenceAuthorityProjectionReadRequest,
        DataObjectActionRequest,
    )


def test__projection_read_request__rejects_oversize() -> None:
    with pytest.raises(CourseReferenceAuthorityError, match="byte limit"):
        SearchReferenceAuthorityProjectionReadRequest(
            expected_sha256="a" * 64,
            expected_byte_size=10_000_001,
            expected_projection_id=(
                "search-reference-authority-projection:sha256:" + "b" * 64
            ),
            expected_projection_result_id=(
                "search-reference-authority-result:sha256:" + "c" * 64
            ),
        )
