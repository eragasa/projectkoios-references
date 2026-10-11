"""Adversarial tests for the repository-local Courses mypy gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.course_architecture_mypy_plugin import (
    course_architecture_violations,
)

_REQUIRED_VIEWS = ("index.md", "schematics.md", "numerics.md", "scientific.md")


def _write_valid_repository(root: Path) -> Path:
    """Write the smallest valid Courses architecture fixture."""
    source_root = root / "src/python/projectkoios/references/courses"
    authority = source_root / "authority"
    runtime = source_root / "runtime"
    authority.mkdir(parents=True)
    runtime.mkdir(parents=True)
    (source_root / "__init__.py").write_text('"""Courses contracts."""\n')
    (authority / "__init__.py").write_text('"""Authority contracts."""\n')
    (runtime / "__init__.py").write_text('"""Runtime contracts."""\n')
    contract = authority / "contract.py"
    contract.write_text(
        """\
from dataclasses import dataclass
from projectkoios.base import DataObjectModel

@dataclass(frozen=True, slots=True, kw_only=True)
class ExampleContract(DataObjectModel):
    \"\"\"Hold one immutable example.\"\"\"
    value: tuple[str, ...]

    def __post_init__(self) -> None:
        \"\"\"Validate the example.\"\"\"
        if not isinstance(self.value, tuple):
            raise TypeError(\"value must be a tuple\")
"""
    )
    test_root = root / "tests/package/projectkoios/references/courses/authority"
    test_root.mkdir(parents=True)
    (test_root / "test__ExampleContract__taxonomy.py").write_text(
        """\
from projectkoios.references.courses.authority.contract import ExampleContract


def test__example_contract__is_public() -> None:
    assert ExampleContract.__name__ == \"ExampleContract\"
"""
    )
    docs = (
        root
        / "docs/architecture/projectkoios/references/courses/authority/contract"
    )
    for directory in (docs, docs / "ExampleContract"):
        directory.mkdir(parents=True)
        for name in _REQUIRED_VIEWS:
            (directory / name).write_text(f"# {name}\n")
    return contract


def _messages(root: Path) -> str:
    """Return fixture diagnostics as one assertion-friendly string."""
    return "\n".join(course_architecture_violations(root))


def test__course_architecture_mypy_plugin__accepts_valid_fixture(
    tmp_path: Path,
) -> None:
    """Accept a frozen, slotted, validation-only public DataObject."""
    _write_valid_repository(tmp_path)
    assert course_architecture_violations(tmp_path) == ()


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    (
        ("class ExampleContract", "class _ExampleContract", "private classes"),
        (
            "class ExampleContract(DataObjectModel):",
            "class ExampleContract(DataObjectModel):\n    class Nested: pass",
            "nested classes",
        ),
        (
            "from dataclasses import dataclass",
            "from dataclasses import dataclass\nfrom elsewhere import _secret",
            "private import _secret is forbidden",
        ),
        (
            "@dataclass(frozen=True, slots=True, kw_only=True)",
            (
                "def public_helper() -> None: pass\n\n"
                "@dataclass(frozen=True, slots=True, kw_only=True)"
            ),
            "public helper functions",
        ),
        ("value: tuple[str, ...]", "value: list[str]", "must be immutable"),
        (
            "@dataclass(frozen=True, slots=True, kw_only=True)",
            "@dataclass(slots=True, kw_only=True)",
            "must be frozen and slotted",
        ),
        (
            "    def __post_init__(self) -> None:",
            (
                "    def execute(self) -> None: pass\n\n"
                "    def __post_init__(self) -> None:"
            ),
            "may only validate",
        ),
        (
            "    def __post_init__(self) -> None:",
            (
                "    @classmethod\n"
                "    def create(cls) -> None: pass\n\n"
                "    def __post_init__(self) -> None:"
            ),
            "classmethod/staticmethod",
        ),
    ),
)
def test__course_architecture_mypy_plugin__rejects_forbidden_source_shapes(
    tmp_path: Path,
    old: str,
    new: str,
    expected: str,
) -> None:
    """Reject each forbidden class, import, function, or field shape."""
    source = _write_valid_repository(tmp_path)
    source.write_text(source.read_text().replace(old, new))
    assert expected in _messages(tmp_path)


def test__course_architecture_mypy_plugin__rejects_private_class(
    tmp_path: Path,
) -> None:
    """Reject a private class even when its base is otherwise allowed."""
    source = _write_valid_repository(tmp_path)
    source.write_text(
        source.read_text().replace(
            "class ExampleContract", "class _ExampleContract"
        )
    )
    assert "private classes" in _messages(tmp_path)


def test__course_architecture_mypy_plugin__rejects_actionizer_extra_method(
    tmp_path: Path,
) -> None:
    """Reject an Actionizer with an executable verb beside action."""
    source = _write_valid_repository(tmp_path)
    source.write_text(
        """\
from projectkoios.base import DataObjectActionizer

class ExampleContract(DataObjectActionizer[object, object]):
    def action(self, *, request: object) -> object:
        return request

    def load(self) -> object:
        return object()
"""
    )
    assert "Actionizer must expose only action" in _messages(tmp_path)


@pytest.mark.parametrize(
    ("source_text", "expected"),
    (
        (
            "class ExampleContract:\n    pass\n",
            "class is outside the allowed taxonomy",
        ),
        (
            """\
from dataclasses import dataclass
from projectkoios.base import DataObjectModel

@dataclass(frozen=True, slots=True)
class ExampleProvider(DataObjectModel):
    value: tuple[str, ...]
""",
            "multi-verb role name is forbidden",
        ),
        (
            """\
from projectkoios.base import DataObjectActionizer

class ExampleContract(DataObjectActionizer[object, object]):
    def action(self, request: object) -> object:
        return request
""",
            "action must consume one keyword-only request",
        ),
        (
            """\
from typing import Protocol

class ExampleContract(Protocol):
    def action(self, *, request: object) -> object: ...
    def load(self) -> object: ...
""",
            "action Protocol must expose only action",
        ),
        (
            """\
from typing import NamedTuple

_PrivateValues = NamedTuple("_PrivateValues", [("value", str)])
""",
            "private NamedTuple declarations are forbidden",
        ),
    ),
)
def test__course_architecture_mypy_plugin__rejects_taxonomy_evasions(
    tmp_path: Path,
    source_text: str,
    expected: str,
) -> None:
    """Reject non-taxonomy roles, signatures, protocols, and tuples."""
    source = _write_valid_repository(tmp_path)
    source.write_text(source_text)
    assert expected in _messages(tmp_path)


def test__course_architecture_mypy_plugin__rejects_initializer_code(
    tmp_path: Path,
) -> None:
    """Reject package initializer behavior or re-exports."""
    _write_valid_repository(tmp_path)
    initializer = (
        tmp_path
        / "src/python/projectkoios/references/courses/authority/__init__.py"
    )
    initializer.write_text('"""Authority contracts."""\nVALUE = 1\n')
    assert "initializer must be docstring-only" in _messages(tmp_path)


def test__course_architecture_mypy_plugin__rejects_missing_test_and_docs(
    tmp_path: Path,
) -> None:
    """Reject a public contract without its dedicated evidence."""
    _write_valid_repository(tmp_path)
    test = next(
        (
            tmp_path / "tests/package/projectkoios/references/courses/authority"
        ).glob("*.py")
    )
    test.unlink()
    class_docs = (
        tmp_path
        / "docs/architecture/projectkoios/references/courses/authority/contract"
        / "ExampleContract"
    )
    for item in class_docs.glob("*.md"):
        item.unlink()
    messages = _messages(tmp_path)
    assert "dedicated class test is missing" in messages
    assert "four-view class architecture node is missing" in messages
