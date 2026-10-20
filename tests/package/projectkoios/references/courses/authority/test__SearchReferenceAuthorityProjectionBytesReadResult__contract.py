"""Search authority projection bytes result contract tests."""

import hashlib

from projectkoios.base import DataObjectActionResult
from projectkoios.references.courses.authority.search_projection import (
    SearchReferenceAuthorityProjectionBytesReadResult,
)


def test__projection_bytes_result__is_action_result() -> None:
    assert issubclass(
        SearchReferenceAuthorityProjectionBytesReadResult,
        DataObjectActionResult,
    )


def test__projection_bytes_result__derives_content_facts() -> None:
    result = SearchReferenceAuthorityProjectionBytesReadResult(
        request_id="test-request:sha256:" + "1" * 64,
        content=b"{}\n",
    )

    assert result.content_byte_size == 3
    assert result.content_sha256 == hashlib.sha256(b"{}\n").hexdigest()
