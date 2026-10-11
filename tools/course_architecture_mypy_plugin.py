"""Repository-local mypy gate for the Courses authority architecture."""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Callable, Iterable
from pathlib import Path

from mypy.options import Options
from mypy.plugin import ClassDefContext, Plugin, ReportConfigContext

_REQUIRED_VIEWS = frozenset(
    {"index.md", "schematics.md", "numerics.md", "scientific.md"}
)
_COURSES_SOURCE = Path("src/python/projectkoios/references/courses")
_COURSES_TESTS = Path("tests/package/projectkoios/references/courses")
_COURSES_DOCS = Path("docs/architecture/projectkoios/references/courses")
_PASSIVE_BASES = frozenset(
    {"DataObjectModel", "DataObjectActionRequest", "DataObjectActionResult"}
)
_ACTIONIZER_BASE = "DataObjectActionizer"
_ENUM_BASES = frozenset({"Enum", "IntEnum", "StrEnum"})
_FORBIDDEN_CLASS_TERMS = (
    "Provider",
    "Service",
    "Manager",
    "Repository",
    "Facade",
    "Helper",
)
_MUTABLE_ANNOTATIONS = frozenset({"dict", "list", "set", "Dict", "List", "Set"})


def _base_name(value: ast.expr) -> str:
    """Return the unqualified name of one base annotation."""
    if isinstance(value, ast.Subscript):
        return _base_name(value.value)
    if isinstance(value, ast.Attribute):
        return value.attr
    if isinstance(value, ast.Name):
        return value.id
    return ast.unparse(value)


def _annotation_has_mutable_container(value: ast.expr | None) -> bool:
    """Return whether an annotation exposes a mutable container."""
    if value is None:
        return False
    return any(
        isinstance(node, (ast.Name, ast.Attribute))
        and (
            (node.id if isinstance(node, ast.Name) else node.attr)
            in _MUTABLE_ANNOTATIONS
        )
        for node in ast.walk(value)
    )


def _dataclass_is_frozen_and_slotted(node: ast.ClassDef) -> bool:
    """Return whether a class has the exact immutable dataclass controls."""
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if _base_name(decorator.func) != "dataclass":
            continue
        keywords = {
            item.arg: item.value for item in decorator.keywords if item.arg
        }
        for name in ("frozen", "slots"):
            value = keywords.get(name)
            if not isinstance(value, ast.Constant) or value.value is not True:
                return False
        return True
    return False


def _class_methods(
    node: ast.ClassDef,
) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...]:
    """Return methods declared directly by one class."""
    return tuple(
        item
        for item in node.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _is_package_initializer_docstring_only(tree: ast.Module) -> bool:
    """Return whether an initializer contains only its module docstring."""
    return (
        len(tree.body) == 1
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    )


def _relative_label(path: Path, repository: Path) -> str:
    """Return a stable repository-relative diagnostic label."""
    try:
        return str(path.relative_to(repository))
    except ValueError:
        return str(path)


def _source_class_violations(
    *,
    node: ast.ClassDef,
    source: Path,
    repository: Path,
    package_name: str,
    module_name: str,
) -> tuple[str, ...]:
    """Return taxonomy violations for one top-level source class."""
    label = f"{_relative_label(source, repository)}:{node.lineno}:{node.name}"
    violations: list[str] = []
    if node.name.startswith("_"):
        violations.append(f"{label}: private classes are forbidden")
    bases = {_base_name(item) for item in node.bases}
    methods = _class_methods(node)
    method_names = {item.name for item in methods}
    if any(
        _base_name(decorator) in {"classmethod", "staticmethod"}
        for method in methods
        for decorator in method.decorator_list
    ):
        violations.append(f"{label}: classmethod/staticmethod is forbidden")
    is_error = node.name.endswith("Error") and bool(
        bases & {"Exception", "RuntimeError", "TypeError", "ValueError"}
    )
    is_enum = bool(bases & _ENUM_BASES)
    is_actionizer = _ACTIONIZER_BASE in bases
    is_passive = bool(bases & _PASSIVE_BASES)
    is_protocol = "Protocol" in bases
    if is_actionizer:
        unexpected = method_names - {"__init__", "action"}
        if "action" not in method_names or unexpected:
            violations.append(
                f"{label}: Actionizer must expose only action and dunders"
            )
        action = next((item for item in methods if item.name == "action"), None)
        if action is not None:
            keyword_names = {item.arg for item in action.args.kwonlyargs}
            if keyword_names != {"request"}:
                violations.append(
                    f"{label}: action must consume one keyword-only request"
                )
            if action.returns is None:
                violations.append(f"{label}: action must declare its Result")
    elif is_passive:
        if not _dataclass_is_frozen_and_slotted(node):
            violations.append(
                f"{label}: passive DataObject must be frozen and slotted"
            )
        if method_names - {"__post_init__"}:
            violations.append(
                f"{label}: passive DataObject may only validate in "
                "__post_init__"
            )
        for statement in node.body:
            if isinstance(
                statement, ast.AnnAssign
            ) and _annotation_has_mutable_container(statement.annotation):
                violations.extend(
                    (f"{label}: passive DataObject fields must be immutable",)
                )
    elif is_protocol:
        if method_names != {"action"}:
            violations.append(
                f"{label}: action Protocol must expose only action"
            )
    elif not (is_error or is_enum):
        violations.append(f"{label}: class is outside the allowed taxonomy")
    if not (is_error or is_enum) and any(
        term in node.name for term in _FORBIDDEN_CLASS_TERMS
    ):
        violations.append(
            f"{label}: multi-verb role name is forbidden for non-error classes"
        )
    test_glob = (
        repository / _COURSES_TESTS / package_name / f"test__{node.name}__*.py"
    )
    if not tuple(test_glob.parent.glob(test_glob.name)):
        violations.append(f"{label}: dedicated class test is missing")
    class_docs = (
        repository / _COURSES_DOCS / package_name / module_name / node.name
    )
    if {item.name for item in class_docs.glob("*.md")} != _REQUIRED_VIEWS:
        violations.append(
            f"{label}: four-view class architecture node is missing"
        )
    return tuple(violations)


def _module_violations(
    *,
    source: Path,
    repository: Path,
    package_name: str,
) -> tuple[str, ...]:
    """Return structural violations for one Courses source module."""
    label = _relative_label(source, repository)
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=label)
    except SyntaxError as error:
        return (f"{label}:{error.lineno or 1}: invalid Python syntax",)
    if source.name == "__init__.py":
        if not _is_package_initializer_docstring_only(tree):
            return (f"{label}: package initializer must be docstring-only",)
        return ()
    violations: list[str] = []
    top_level_classes = {
        id(item) for item in tree.body if isinstance(item, ast.ClassDef)
    }
    for item in ast.walk(tree):
        if isinstance(item, ast.ClassDef) and id(item) not in top_level_classes:
            violations.append(
                f"{label}:{item.lineno}:{item.name}: nested classes are "
                "forbidden"
            )
        if isinstance(item, ast.ImportFrom):
            for imported in item.names:
                if imported.name.startswith(
                    "_"
                ) and not imported.name.startswith("__"):
                    violations.extend(
                        (
                            (
                                f"{label}:{item.lineno}: private import "
                                f"{imported.name} is forbidden"
                            ),
                        )
                    )
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not (
            item.name.startswith("_")
        ):
            violations.append(
                f"{label}:{item.lineno}:{item.name}: public helper functions "
                "are forbidden"
            )
        assignment_name: str | None = None
        assignment_value: ast.expr | None = None
        if isinstance(item, ast.Assign) and len(item.targets) == 1:
            target = item.targets[0]
            if isinstance(target, ast.Name):
                assignment_name = target.id
                assignment_value = item.value
        elif isinstance(item, ast.AnnAssign):
            if isinstance(item.target, ast.Name):
                assignment_name = item.target.id
                assignment_value = item.value
        if (
            assignment_name is not None
            and assignment_name.startswith("_")
            and isinstance(assignment_value, ast.Call)
            and _base_name(assignment_value.func) == "NamedTuple"
        ):
            violations.append(
                f"{label}:{item.lineno}:{assignment_name}: private "
                "NamedTuple declarations are forbidden"
            )
        if isinstance(item, ast.ClassDef):
            violations.extend(
                _source_class_violations(
                    node=item,
                    source=source,
                    repository=repository,
                    package_name=package_name,
                    module_name=source.stem,
                )
            )
    module_docs = repository / _COURSES_DOCS / package_name / source.stem
    if (
        source.name != "__init__.py"
        and {item.name for item in module_docs.glob("*.md")} != _REQUIRED_VIEWS
    ):
        violations.append(
            f"{label}: four-view module architecture node is missing"
        )
    return tuple(violations)


def _test_violations(*, test: Path, repository: Path) -> tuple[str, ...]:
    """Return forbidden-shape violations for one Courses test module."""
    label = _relative_label(test, repository)
    try:
        tree = ast.parse(test.read_text(encoding="utf-8"), filename=label)
    except SyntaxError as error:
        return (f"{label}:{error.lineno or 1}: invalid Python syntax",)
    violations: list[str] = []
    top_level_classes = {
        id(item) for item in tree.body if isinstance(item, ast.ClassDef)
    }
    for item in ast.walk(tree):
        if isinstance(item, ast.ClassDef):
            if item.name.startswith("_"):
                violations.extend(
                    (
                        (
                            f"{label}:{item.lineno}:{item.name}: private test "
                            "classes are forbidden"
                        ),
                    )
                )
            if id(item) not in top_level_classes:
                violations.extend(
                    (
                        (
                            f"{label}:{item.lineno}:{item.name}: nested test "
                            "classes are forbidden"
                        ),
                    )
                )
        if isinstance(item, ast.ImportFrom):
            for imported in item.names:
                if imported.name.startswith(
                    "_"
                ) and not imported.name.startswith("__"):
                    violations.extend(
                        (
                            (
                                f"{label}:{item.lineno}: tests cannot import "
                                "private names"
                            ),
                        )
                    )
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not (
            item.name.startswith("test_") or item.name.startswith("_")
        ):
            violations.extend(
                (
                    (
                        f"{label}:{item.lineno}:{item.name}: public helper "
                        "is forbidden in tests"
                    ),
                )
            )
    return tuple(violations)


def course_architecture_violations(repository: Path) -> tuple[str, ...]:
    """Return deterministic violations for the complete Courses boundary."""
    violations: list[str] = []
    source_root = repository / _COURSES_SOURCE
    test_root = repository / _COURSES_TESTS
    for package_name in ("authority", "runtime", "transport"):
        package = source_root / package_name
        for source in sorted(package.glob("*.py")):
            violations.extend(
                _module_violations(
                    source=source,
                    repository=repository,
                    package_name=package_name,
                )
            )
        for test in sorted((test_root / package_name).glob("*.py")):
            violations.extend(
                _test_violations(test=test, repository=repository)
            )
    courses_initializer = source_root / "__init__.py"
    if courses_initializer.exists():
        violations.extend(
            _module_violations(
                source=courses_initializer,
                repository=repository,
                package_name="",
            )
        )
    return tuple(sorted(set(violations)))


def _architecture_digest(repository: Path) -> str:
    """Return a cache key for source, test, and architecture evidence."""
    digest = hashlib.sha256()
    roots: Iterable[Path] = (
        repository / _COURSES_SOURCE,
        repository / _COURSES_TESTS,
        repository / _COURSES_DOCS,
    )
    for root in roots:
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            digest.update(str(path.relative_to(repository)).encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


class CourseArchitecturePlugin(Plugin):
    """Make strict mypy the authoritative Courses architecture gate."""

    def __init__(self, options: Options) -> None:
        """Capture deterministic repository-local gate evidence."""
        super().__init__(options)
        self._repository = Path(__file__).resolve().parent.parent
        self._violations = course_architecture_violations(self._repository)
        self._reported = False

    def get_customize_class_mro_hook(
        self,
        fullname: str,
    ) -> Callable[[ClassDefContext], None] | None:
        """Report repository violations during Courses semantic analysis."""
        if not fullname.startswith("projectkoios.references.courses."):
            return None
        return self._report

    def _report(self, context: ClassDefContext) -> None:
        """Emit each repository-local diagnostic once per mypy run."""
        if self._reported:
            return
        self._reported = True
        for violation in self._violations:
            context.api.fail(f"courses-taxonomy: {violation}", context.cls)

    def report_config_data(self, context: ReportConfigContext) -> object:
        """Invalidate mypy caches when architecture evidence changes."""
        del context
        return {"courses_architecture": _architecture_digest(self._repository)}


def plugin(version: str) -> type[CourseArchitecturePlugin]:
    """Return the repository-local plugin type for mypy discovery."""
    del version
    return CourseArchitecturePlugin
