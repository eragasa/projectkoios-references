"""Filesystem Search authority projection bytes adapter tests."""

from __future__ import annotations

import hashlib
from dataclasses import fields
from pathlib import Path, PurePosixPath

import pytest
from projectkoios.base import DataObjectActionizer
from projectkoios.references.courses.authority.search_projection import (
    SearchReferenceAuthorityProjectionReadActionizer,
    SearchReferenceAuthorityProjectionReadError,
    SearchReferenceAuthorityProjectionReadRequest,
)
from projectkoios.references.courses.runtime.filesystem import (
    FilesystemSearchReferenceAuthorityProjectionBytesReadActionizer,
)
from projectkoios.references.path_safety import (
    PlaceholderProbeSupport,
    PlaceholderStatus,
    RootStorageClass,
)

_FIXTURE = (
    Path(__file__).parents[5]
    / "fixtures"
    / "search-reference-authority-projection.json"
)
_PROJECTION_ID = (
    "search-reference-authority-projection:sha256:"
    "4bfe2c6354f74bfa8501cfcc7546db32311ee69f6a81ea0e075dd3919b358302"
)
_PROJECTION_RESULT_ID = (
    "search-reference-authority-result:sha256:"
    "3b6857b84357d731b276204eb38d9352d51d66b7476c344c1aedefb0270a49e5"
)


class MissingSearchAuthorityPlaceholderProbe:
    """Report every candidate as an unavailable placeholder."""

    probe_id = "missing-search-authority-fixture-v1"

    def support(self, *, root_alias: str) -> PlaceholderProbeSupport:
        del root_alias
        return PlaceholderProbeSupport.SUPPORTED

    def observe(
        self,
        *,
        root_alias: str,
        relative_path: PurePosixPath,
    ) -> PlaceholderStatus:
        del root_alias, relative_path
        return PlaceholderStatus.MISSING


def _request(content: bytes) -> SearchReferenceAuthorityProjectionReadRequest:
    return SearchReferenceAuthorityProjectionReadRequest(
        expected_sha256=hashlib.sha256(content).hexdigest(),
        expected_byte_size=len(content),
        expected_projection_id=_PROJECTION_ID,
        expected_projection_result_id=_PROJECTION_RESULT_ID,
    )


def _adapter(
    path: Path,
    *,
    root_alias: str,
) -> FilesystemSearchReferenceAuthorityProjectionBytesReadActionizer:
    return FilesystemSearchReferenceAuthorityProjectionBytesReadActionizer(
        path=path,
        root_alias=root_alias,
        storage_class=RootStorageClass.LOCAL,
    )


def test__filesystem_projection_read__is_actionizer() -> None:
    assert issubclass(
        FilesystemSearchReferenceAuthorityProjectionBytesReadActionizer,
        DataObjectActionizer,
    )


def test__filesystem_projection_read__loads_exact_projection(
    tmp_path: Path,
) -> None:
    content = _FIXTURE.read_bytes()
    path = tmp_path / "authority.json"
    path.write_bytes(content)
    request = _request(content)

    result = SearchReferenceAuthorityProjectionReadActionizer(
        source=_adapter(path, root_alias="search-authority-test")
    ).action(request=request)

    assert result.request_id == request.request_id
    assert result.projection.projection_id == _PROJECTION_ID
    assert str(tmp_path) not in repr(result)
    semantic_names = {item.name for item in (*fields(request), *fields(result))}
    assert semantic_names.isdisjoint(
        {"path", "root", "root_alias", "storage_class", "placeholder_probe"}
    )


def test__filesystem_projection_read__is_root_neutral(
    tmp_path: Path,
) -> None:
    content = _FIXTURE.read_bytes()
    first_path = tmp_path / "first" / "authority.json"
    second_path = tmp_path / "second" / "projection.json"
    first_path.parent.mkdir()
    second_path.parent.mkdir()
    first_path.write_bytes(content)
    second_path.write_bytes(content)
    request = _request(content)
    first_source = _adapter(first_path, root_alias="first-authority-root")
    second_source = _adapter(second_path, root_alias="second-authority-root")

    first_bytes = first_source.action(request=request)
    second_bytes = second_source.action(request=request)
    first = SearchReferenceAuthorityProjectionReadActionizer(
        source=first_source
    ).action(request=request)
    second = SearchReferenceAuthorityProjectionReadActionizer(
        source=second_source
    ).action(request=request)

    assert first_bytes == second_bytes
    assert first == second
    assert first.result_id == second.result_id
    assert str(first_path) not in repr(first)
    assert str(second_path) not in repr(second)


def _failure(
    adapter: FilesystemSearchReferenceAuthorityProjectionBytesReadActionizer,
    *,
    content: bytes,
) -> SearchReferenceAuthorityProjectionReadError:
    with pytest.raises(SearchReferenceAuthorityProjectionReadError) as caught:
        adapter.action(request=_request(content))
    return caught.value


def _assert_path_free_failure(
    error: SearchReferenceAuthorityProjectionReadError,
    *,
    sentinels: tuple[str, ...],
) -> None:
    assert type(error) is SearchReferenceAuthorityProjectionReadError
    assert error.code == "search-reference-authority-projection-unavailable"
    assert error.args == (
        "Search reference authority projection is unavailable",
    )
    graph: list[BaseException] = [error]
    seen: set[int] = set()
    while graph:
        current = graph.pop()
        assert id(current) not in seen
        seen.add(id(current))
        exposed = [str(current), repr(current), repr(current.args)]
        exposed.extend(repr(value) for value in vars(current).values())
        for name in dir(current):
            if name.startswith("_") or name in {"add_note", "with_traceback"}:
                continue
            value = getattr(current, name)
            if not callable(value):
                exposed.append(repr(value))
        rendered = "\n".join(exposed)
        assert not any(sentinel in rendered for sentinel in sentinels)
        graph.extend(
            linked
            for linked in (current.__cause__, current.__context__)
            if linked is not None
        )
    assert len(seen) == 1
    assert error.__cause__ is None
    assert error.__context__ is None
    frame_names: list[str] = []
    traceback = error.__traceback__
    while traceback is not None:
        frame = traceback.tb_frame
        if frame.f_globals.get("__name__") == (
            "projectkoios.references.courses.runtime.filesystem"
        ):
            frame_names.append(frame.f_code.co_name)
            rendered_locals = "\n".join(
                f"{name}={value!r}" for name, value in frame.f_locals.items()
            )
            assert not any(
                sentinel in rendered_locals for sentinel in sentinels
            )
        traceback = traceback.tb_next
    assert "read_path_bytes" not in frame_names


def test__filesystem_projection_read__redacts_missing_parent(
    tmp_path: Path,
) -> None:
    content = _FIXTURE.read_bytes()
    root_alias = "missing-parent-authority-root"
    path = tmp_path / "private-parent-sentinel" / "authority.json"

    error = _failure(_adapter(path, root_alias=root_alias), content=content)

    _assert_path_free_failure(
        error,
        sentinels=(str(tmp_path), "private-parent-sentinel", root_alias),
    )


def test__filesystem_projection_read__redacts_missing_leaf(
    tmp_path: Path,
) -> None:
    content = _FIXTURE.read_bytes()
    root_alias = "missing-leaf-authority-root"
    leaf = "private-missing-leaf-sentinel.json"
    path = tmp_path / leaf

    error = _failure(_adapter(path, root_alias=root_alias), content=content)

    _assert_path_free_failure(
        error,
        sentinels=(str(tmp_path), leaf, root_alias),
    )


def test__filesystem_projection_read__redacts_root_symlink(
    tmp_path: Path,
) -> None:
    content = _FIXTURE.read_bytes()
    root_alias = "root-symlink-authority-root"
    target = tmp_path / "real-root"
    target.mkdir()
    (target / "authority.json").write_bytes(content)
    root = tmp_path / "private-root-symlink-sentinel"
    root.symlink_to(target, target_is_directory=True)

    error = _failure(
        _adapter(root / "authority.json", root_alias=root_alias),
        content=content,
    )

    _assert_path_free_failure(
        error,
        sentinels=(str(tmp_path), root.name, root_alias),
    )


def test__filesystem_projection_read__redacts_intermediate_symlink(
    tmp_path: Path,
) -> None:
    content = _FIXTURE.read_bytes()
    root_alias = "intermediate-symlink-authority-root"
    target = tmp_path / "real-intermediate"
    target.mkdir()
    (target / "authority.json").write_bytes(content)
    parent = tmp_path / "parent"
    parent.mkdir()
    intermediate = parent / "private-intermediate-symlink-sentinel"
    intermediate.symlink_to(target, target_is_directory=True)

    error = _failure(
        _adapter(intermediate / "authority.json", root_alias=root_alias),
        content=content,
    )

    _assert_path_free_failure(
        error,
        sentinels=(str(tmp_path), intermediate.name, root_alias),
    )


def test__filesystem_projection_read__redacts_final_symlink(
    tmp_path: Path,
) -> None:
    content = _FIXTURE.read_bytes()
    root_alias = "final-symlink-authority-root"
    target = tmp_path / "target.json"
    target.write_bytes(content)
    leaf = "private-final-symlink-sentinel.json"
    link = tmp_path / leaf
    link.symlink_to(target)

    error = _failure(_adapter(link, root_alias=root_alias), content=content)

    _assert_path_free_failure(
        error,
        sentinels=(str(tmp_path), leaf, root_alias),
    )


def test__filesystem_projection_read__redacts_placeholder(
    tmp_path: Path,
) -> None:
    content = _FIXTURE.read_bytes()
    leaf = "private-placeholder-sentinel.json"
    path = tmp_path / leaf
    path.write_bytes(content)
    root_alias = "placeholder-authority-root"
    adapter = FilesystemSearchReferenceAuthorityProjectionBytesReadActionizer(
        path=path,
        root_alias=root_alias,
        storage_class=RootStorageClass.CLOUD_BACKED,
        placeholder_probe=MissingSearchAuthorityPlaceholderProbe(),
    )

    error = _failure(adapter, content=content)

    _assert_path_free_failure(
        error,
        sentinels=(str(tmp_path), leaf, root_alias),
    )


def test__filesystem_projection_read__redacts_oversize_file(
    tmp_path: Path,
) -> None:
    content = _FIXTURE.read_bytes()
    leaf = "private-oversize-sentinel.json"
    path = tmp_path / leaf
    path.write_bytes(content + b" ")
    root_alias = "oversize-authority-root"

    error = _failure(_adapter(path, root_alias=root_alias), content=content)

    _assert_path_free_failure(
        error,
        sentinels=(str(tmp_path), leaf, root_alias),
    )


def test__filesystem_projection_read__redacts_permission_failure(
    tmp_path: Path,
) -> None:
    content = _FIXTURE.read_bytes()
    leaf = "private-permission-sentinel.json"
    path = tmp_path / leaf
    path.write_bytes(content)
    path.chmod(0o000)
    root_alias = "permission-authority-root"
    try:
        error = _failure(
            _adapter(path, root_alias=root_alias),
            content=content,
        )
    finally:
        path.chmod(0o600)

    _assert_path_free_failure(
        error,
        sentinels=(str(tmp_path), leaf, root_alias),
    )
