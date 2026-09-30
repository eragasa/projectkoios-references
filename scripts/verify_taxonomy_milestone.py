#!/usr/bin/env python3.14
"""Verify the bounded References taxonomy milestone without provisioning."""

from __future__ import annotations

import argparse
import atexit
import configparser
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import tomllib
import zipfile
from pathlib import Path
from types import FrameType
from typing import Any

EXPECTED_OWNER_COMMIT = "233f36900b9b44c943ecc5e27f2968ad4bee97ad"
EXPECTED_OWNER_TREE = "b7c3ffd23086e7ef184c990267d48a56dd87282b"
EXPECTED_BASE_SHA256 = (
    "8273f29ad57c6cefab73a26274b45ea58d28083644ab165a73c6195a0299346a"
)
OWNER_GIT_URL = "https://github.com/eragasa/projectkoios.git"
EXPECTED_TOOL_VERSIONS = {
    "mypy": "2.3.1",
    "pytest": "9.1.1",
    "python": "3.14.6",
    "ruff": "0.16.9",
    "setuptools": "84.0.0",
    "uv": "0.11.25",
}
OWNER_COMMIT_BODY = (
    b"tree b7c3ffd23086e7ef184c990267d48a56dd87282b\n"
    b"parent 2edf0af51a2f60eaa946afdde051484c4cd4e167\n"
    b"author Eugene Joseph M. Ragasa <eugene@projectkoios.com> "
    b"1790760069 +0800\n"
    b"committer Eugene Joseph M. Ragasa <eugene@projectkoios.com> "
    b"1790760069 +0800\n"
    b"\n"
    b"feat: define thin data object base ABCs\n"
)
FOCUSED_TESTS = (
    "tests/test__AcquisitionManifest.py",
    "tests/test__AssetDiscovery.py",
    "tests/test__CitationClosure.py",
    "tests/test__CitationDraft.py",
    "tests/test__CitationGraph.py",
    "tests/test__CloudPlaceholderSafety.py",
    "tests/test__CoverageObservation.py",
    "tests/test__IOBounds.py",
    "tests/test__IngestionEvidence.py",
    "tests/test__ReferenceFilenames.py",
)


class VerificationError(RuntimeError):
    """Report a fail-closed milestone verification error."""


class TaxonomyMilestoneVerifier:
    """Run the exact repository-owner verification sequence."""

    def __init__(
        self,
        *,
        repository: Path,
        python: Path,
        uv: str,
        owner_commit: str,
        owner_tree: str,
    ) -> None:
        self.repository = repository
        self.python = python
        self.uv = uv
        self.owner_commit = owner_commit
        self.owner_tree = owner_tree
        self.temporary_root: Path | None = None

    def verify(self) -> None:
        """Run all checks and remove every temporary artifact."""
        self._print_contract()
        self._verify_inputs()
        self.temporary_root = Path(
            tempfile.mkdtemp(prefix="projectkoios-references-verify-")
        )
        atexit.register(self._cleanup)
        previous_handlers = self._install_signal_cleanup()
        try:
            environment = self._environment()
            self._verify_tool_environment(environment)
            self._verify_owner_runtime(environment)
            self._run_focused_tests(environment)
            self._run_source_checks(environment)
            wheel = self._build_from_committed_tree(environment)
            self._run_wheel_import_smoke(wheel, environment)
            self._print_artifact_evidence(wheel)
            self._require_clean_tree()
        finally:
            self._restore_signal_handlers(previous_handlers)
            self._cleanup()
        print("RESULT: verified")

    def _print_contract(self) -> None:
        print("Project Koios References taxonomy milestone verification")
        print("INPUT owner commit:", self.owner_commit)
        print("INPUT owner tree:", self.owner_tree)
        print("INPUT Python:", self.python)
        print("INPUT uv:", self.uv)
        print("EFFECTS: reads tracked source and the provisioned environment")
        print("EFFECTS: writes only trap-cleaned operating-system temp files")
        print("SAFETY: offline, no dependency installation, no private data")
        print(
            "STOPS: dirty Git tree, identity drift, missing tools, "
            "or check failure"
        )
        print(
            "REUSE LIMIT: this script verifies only the current References "
            "taxonomy/CLI milestone and exact owner source"
        )
        sys.stdout.flush()

    def _verify_inputs(self) -> None:
        if self.owner_commit != EXPECTED_OWNER_COMMIT:
            raise VerificationError("owner commit differs from the milestone")
        if self.owner_tree != EXPECTED_OWNER_TREE:
            raise VerificationError("owner tree differs from the milestone")
        if not self.python.is_file():
            raise VerificationError("provisioned Python executable is missing")
        self._require_clean_tree()
        head = self._capture(("git", "rev-parse", "HEAD"))
        tree = self._capture(("git", "rev-parse", "HEAD^{tree}"))
        script_stage = self._capture(
            (
                "git",
                "ls-files",
                "--stage",
                "scripts/verify_taxonomy_milestone.py",
            )
        )
        if not script_stage.startswith("100755 "):
            raise VerificationError(
                "verification script must be committed and executable"
            )
        print("EVIDENCE repository commit:", head)
        print("EVIDENCE repository tree:", tree)

        commit_object = (
            b"commit "
            + str(len(OWNER_COMMIT_BODY)).encode("ascii")
            + b"\0"
            + OWNER_COMMIT_BODY
        )
        published_commit = hashlib.sha1(commit_object).hexdigest()
        published_tree = OWNER_COMMIT_BODY.splitlines()[0].split()[1].decode()
        if published_commit != self.owner_commit:
            raise VerificationError("published owner commit payload is invalid")
        if published_tree != self.owner_tree:
            raise VerificationError(
                "published owner commit/tree pair is invalid"
            )

        pyproject = tomllib.loads(
            (self.repository / "pyproject.toml").read_text(encoding="utf-8")
        )
        dependencies = pyproject["project"]["dependencies"]
        if "projectkoios==0.0.0" not in dependencies:
            raise VerificationError(
                "exact projectkoios runtime version is absent"
            )
        source = pyproject["tool"]["uv"]["sources"]["projectkoios"]
        expected_source = {"git": OWNER_GIT_URL, "rev": self.owner_commit}
        if source != expected_source:
            raise VerificationError("pyproject owner source is not exact")

        lock = (self.repository / "uv.lock").read_text(encoding="utf-8")
        pinned = f"{OWNER_GIT_URL}?rev={self.owner_commit}#{self.owner_commit}"
        if pinned not in lock:
            raise VerificationError("lockfile owner revision is not exact")

    def _environment(self) -> dict[str, str]:
        if self.temporary_root is None:
            raise VerificationError("temporary root is unavailable")
        environment = os.environ.copy()
        environment.update(
            {
                "MYPY_CACHE_DIR": str(self.temporary_root / "mypy-cache"),
                "PIP_NO_INDEX": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
                "PYTHONPATH": (
                    f"{self.repository / 'src/python'}{os.pathsep}"
                    f"{self.repository}"
                ),
                "RUFF_CACHE_DIR": str(self.temporary_root / "ruff-cache"),
                "SOURCE_DATE_EPOCH": self._capture(
                    ("git", "show", "-s", "--format=%ct", "HEAD")
                ).strip(),
                "UV_NO_INDEX": "1",
                "UV_OFFLINE": "1",
                "UV_PYTHON_DOWNLOADS": "never",
            }
        )
        return environment

    def _verify_tool_environment(self, environment: dict[str, str]) -> None:
        probe = textwrap.dedent(
            """
            import json
            import platform
            from importlib.metadata import version

            import mypy.version
            import pytest
            import ruff
            import setuptools

            del ruff
            print(json.dumps({
                "mypy": mypy.version.__version__,
                "pytest": pytest.__version__,
                "python": platform.python_version(),
                "ruff": version("ruff"),
                "setuptools": setuptools.__version__,
            }, sort_keys=True))
            """
        )
        evidence = json.loads(
            self._capture(
                (str(self.python), "-c", probe),
                environment=environment,
            )
        )
        uv_output = self._capture((self.uv, "--version"))
        uv_parts = uv_output.split()
        if len(uv_parts) < 2:
            raise VerificationError("uv version output is malformed")
        evidence["uv"] = uv_parts[1]
        if evidence != EXPECTED_TOOL_VERSIONS:
            raise VerificationError("provisioned tool versions drifted")
        print("EVIDENCE tools:", json.dumps(evidence, sort_keys=True))

    def _verify_owner_runtime(self, environment: dict[str, str]) -> None:
        probe = textwrap.dedent(
            """
            import hashlib
            import json
            from importlib.metadata import distribution
            from pathlib import Path

            import projectkoios.base

            direct_path = distribution("projectkoios").locate_file(
                "projectkoios-0.0.0.dist-info/direct_url.json"
            )
            direct = json.loads(direct_path.read_text(encoding="utf-8"))
            base_sha256 = hashlib.sha256(
                Path(projectkoios.base.__file__).read_bytes()
            ).hexdigest()
            print(json.dumps({
                "base_sha256": base_sha256,
                "commit": direct["vcs_info"]["commit_id"],
                "requested_revision": direct["vcs_info"][
                    "requested_revision"
                ],
                "url": direct["url"],
            }, sort_keys=True))
            """
        )
        evidence = json.loads(
            self._capture(
                (str(self.python), "-c", probe),
                environment=environment,
            )
        )
        expected = {
            "base_sha256": EXPECTED_BASE_SHA256,
            "commit": self.owner_commit,
            "requested_revision": self.owner_commit,
            "url": OWNER_GIT_URL,
        }
        if evidence != expected:
            raise VerificationError(
                "provisioned owner runtime identity drifted"
            )
        print("EVIDENCE owner runtime:", json.dumps(evidence, sort_keys=True))

    def _run_focused_tests(self, environment: dict[str, str]) -> None:
        self._run(
            (
                str(self.python),
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                *FOCUSED_TESTS,
            ),
            environment=environment,
        )

    def _run_source_checks(self, environment: dict[str, str]) -> None:
        self._run(
            (str(self.python), "-m", "mypy", "src/python", "scripts"),
            environment=environment,
        )
        self._run(
            (
                str(self.python),
                "-m",
                "ruff",
                "check",
                "--no-cache",
                "src/python",
                "scripts",
                "tests",
            ),
            environment=environment,
        )
        self._run(
            (
                str(self.python),
                "-m",
                "ruff",
                "format",
                "--check",
                "--no-cache",
                "src/python",
                "scripts",
                "tests",
            ),
            environment=environment,
        )

    def _build_from_committed_tree(
        self,
        environment: dict[str, str],
    ) -> Path:
        if self.temporary_root is None:
            raise VerificationError("temporary root is unavailable")
        archive = self.temporary_root / "source.tar"
        source = self.temporary_root / "source"
        distribution_directory = self.temporary_root / "dist"
        archive.write_bytes(
            subprocess.check_output(
                ("git", "archive", "--format=tar", "HEAD"),
                cwd=self.repository,
                env=environment,
            )
        )
        source.mkdir()
        with tarfile.open(archive, mode="r:") as bundle:
            unsafe = [
                member.name
                for member in bundle.getmembers()
                if not (member.isfile() or member.isdir())
            ]
            if unsafe:
                raise VerificationError(
                    f"committed archive contains unsupported members: {unsafe}"
                )
            bundle.extractall(source, filter="data")
        self._run(
            (
                self.uv,
                "build",
                "--offline",
                "--no-index",
                "--no-python-downloads",
                "--no-build-isolation",
                "--no-build-logs",
                "--no-create-gitignore",
                "--wheel",
                "--python",
                str(self.python),
                "--out-dir",
                str(distribution_directory),
                str(source),
            ),
            environment=environment,
        )
        artifacts = tuple(distribution_directory.iterdir())
        wheels = tuple(distribution_directory.glob("*.whl"))
        if len(artifacts) != 1 or len(wheels) != 1 or artifacts[0] != wheels[0]:
            raise VerificationError("build did not produce exactly one wheel")
        return wheels[0]

    def _run_wheel_import_smoke(
        self,
        wheel: Path,
        environment: dict[str, str],
    ) -> None:
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
            if "projectkoios/references/cli.py" in names:
                raise VerificationError("wheel contains removed package CLI")
            entry_name = next(
                (
                    name
                    for name in names
                    if name.endswith(".dist-info/entry_points.txt")
                ),
                None,
            )
            metadata_name = next(
                (
                    name
                    for name in names
                    if name.endswith(".dist-info/METADATA")
                ),
                None,
            )
            if entry_name is None or metadata_name is None:
                raise VerificationError("wheel metadata is incomplete")
            parser = configparser.ConfigParser()
            parser.read_string(archive.read(entry_name).decode("utf-8"))
            if parser["console_scripts"].get("koios-ref") != (
                "scripts.koios_ref:main"
            ):
                raise VerificationError("wheel entry point drifted")
            metadata = archive.read(metadata_name).decode("utf-8")
            if "Requires-Dist: projectkoios==0.0.0" not in metadata:
                raise VerificationError("wheel runtime dependency drifted")

        smoke = textwrap.dedent(
            """
            import contextlib
            import io
            import json
            import sys

            wheel = sys.argv[1]
            sys.path.insert(0, wheel)

            from projectkoios.base import DataObjectActionizer, DataObjectModel
            from projectkoios.references import ReferenceFilenames
            from projectkoios.references.citation_draft import (
                CitationDraftParser,
                CitationDraftRenderer,
            )
            import projectkoios.references.naming as naming
            import scripts.koios_ref as operator_script

            if not issubclass(ReferenceFilenames, DataObjectModel):
                raise SystemExit("ReferenceFilenames base drifted")
            if not issubclass(CitationDraftParser, DataObjectActionizer):
                raise SystemExit("parser base drifted")
            if not issubclass(CitationDraftRenderer, DataObjectActionizer):
                raise SystemExit("renderer base drifted")
            if (
                wheel not in naming.__file__
                or wheel not in operator_script.__file__
            ):
                raise SystemExit("smoke import did not use the built wheel")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                try:
                    operator_script.main(["--help"])
                except SystemExit as error:
                    if error.code != 0:
                        raise
            if not output.getvalue().startswith("usage: koios-ref"):
                raise SystemExit("operator help smoke failed")
            print(json.dumps({
                "entry_point": "scripts.koios_ref:main",
                "filenames_base": ReferenceFilenames.__mro__[1].__name__,
                "package_cli_absent": True,
            }, sort_keys=True))
            """
        )
        smoke_environment = environment.copy()
        smoke_environment["PYTHONPATH"] = str(wheel)
        output = self._capture(
            (str(self.python), "-c", smoke, str(wheel)),
            cwd=self.temporary_root,
            environment=smoke_environment,
        )
        print("EVIDENCE wheel smoke:", output.strip())

    @staticmethod
    def _print_artifact_evidence(wheel: Path) -> None:
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        print(f"EVIDENCE wheel sha256: {digest}")

    def _require_clean_tree(self) -> None:
        status = self._capture(
            (
                "git",
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            )
        )
        if status:
            raise VerificationError("Git tree must be clean")

    def _capture(
        self,
        command: tuple[str, ...],
        *,
        cwd: Path | None = None,
        environment: dict[str, str] | None = None,
    ) -> str:
        completed = subprocess.run(
            command,
            cwd=cwd or self.repository,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise VerificationError(
                f"command failed ({completed.returncode}): {command[0]} "
                f"{command[1] if len(command) > 1 else ''}\n"
                f"{completed.stdout}{completed.stderr}"
            )
        return completed.stdout.strip()

    def _run(
        self,
        command: tuple[str, ...],
        *,
        cwd: Path | None = None,
        environment: dict[str, str],
    ) -> None:
        completed = subprocess.run(
            command,
            cwd=cwd or self.repository,
            env=environment,
            check=False,
        )
        if completed.returncode != 0:
            raise VerificationError(
                f"command failed ({completed.returncode}): {command[0]} "
                f"{command[1] if len(command) > 1 else ''}"
            )

    def _install_signal_cleanup(
        self,
    ) -> dict[signal.Signals, Any]:
        previous: dict[signal.Signals, Any] = {}

        def interrupt(signum: int, frame: FrameType | None) -> None:
            del frame
            raise VerificationError(f"interrupted by signal {signum}")

        for name in ("SIGINT", "SIGTERM", "SIGHUP"):
            if hasattr(signal, name):
                selected = signal.Signals(getattr(signal, name))
                previous[selected] = signal.getsignal(selected)
                signal.signal(selected, interrupt)
        return previous

    @staticmethod
    def _restore_signal_handlers(
        previous: dict[signal.Signals, Any],
    ) -> None:
        for selected, handler in previous.items():
            signal.signal(selected, handler)

    def _cleanup(self) -> None:
        if self.temporary_root is not None:
            shutil.rmtree(self.temporary_root, ignore_errors=True)
            self.temporary_root = None


def parse_arguments(arguments: list[str]) -> argparse.Namespace:
    """Parse the exact milestone identity and provisioned-tool inputs."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner-commit", required=True)
    parser.add_argument("--owner-tree", required=True)
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(".venv/bin/python"),
        help="existing provisioned Python 3.14 executable",
    )
    parser.add_argument(
        "--uv",
        default="uv",
        help=(
            "existing uv executable used only for an offline no-isolation build"
        ),
    )
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    """Verify the exact bounded milestone and fail closed on drift."""
    options = parse_arguments(sys.argv[1:] if arguments is None else arguments)
    repository = Path(__file__).resolve().parents[1]
    python = options.python
    if not python.is_absolute():
        python = (repository / python).absolute()
    try:
        TaxonomyMilestoneVerifier(
            repository=repository,
            python=python,
            uv=options.uv,
            owner_commit=options.owner_commit,
            owner_tree=options.owner_tree,
        ).verify()
    except (OSError, VerificationError, subprocess.SubprocessError) as error:
        print(f"VERIFY FAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
