from __future__ import annotations

import errno
import os
import secrets
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Never

_CITEKEY_MAX_LENGTH = 200
_WINDOWS_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)
_CITEKEY_ASCII = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
)
_PORTABLE_FORBIDDEN = frozenset('<>:"\\|?*')
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_FLAGS = (
    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
)


class PathSafetyError(ValueError):
    """Raised when a path cannot be used within an authorized root."""


def validate_citekey(value: object, *, field: str = "citekey") -> str:
    """Return one portable, filesystem-safe citation key."""
    if not isinstance(value, str) or not value:
        raise PathSafetyError(f"{field} must be a non-empty string")
    if value != unicodedata.normalize("NFC", value):
        raise PathSafetyError(f"{field} must use NFC normalization")
    if len(value) > _CITEKEY_MAX_LENGTH:
        raise PathSafetyError(f"{field} exceeds the portable length limit")
    if not value[0].isascii() or not value[0].isalpha():
        raise PathSafetyError(f"{field} must start with an ASCII letter")
    if any(character not in _CITEKEY_ASCII for character in value):
        raise PathSafetyError(
            f"{field} may contain only ASCII letters, numbers, period, "
            "underscore, or hyphen"
        )
    if value.endswith("."):
        raise PathSafetyError(f"{field} must not end with a period")
    if value.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        raise PathSafetyError(f"{field} is a reserved portable filename")
    return value


def validate_root_alias(value: object, *, field: str = "root_alias") -> str:
    """Return one portable root-alias segment."""
    if not isinstance(value, str) or not value:
        raise PathSafetyError(f"{field} must be a non-empty string")
    if value != unicodedata.normalize("NFC", value):
        raise PathSafetyError(f"{field} must use NFC normalization")
    if len(value) > 100:
        raise PathSafetyError(f"{field} exceeds the portable length limit")
    if "/" in value or "\\" in value:
        raise PathSafetyError(f"{field} must be one portable path segment")
    _validate_portable_segment(value, field=field)
    return value


def validate_relative_path(
    value: str | PurePosixPath,
    *,
    field: str = "relative_path",
) -> PurePosixPath:
    """Return a normalized portable relative path without traversal."""
    raw = value.as_posix() if isinstance(value, PurePosixPath) else value
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise PathSafetyError(
            f"{field} must be a normalized portable relative path"
        )
    if raw != unicodedata.normalize("NFC", raw):
        raise PathSafetyError(f"{field} must use NFC normalization")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != raw
    ):
        raise PathSafetyError(
            f"{field} must be normalized, relative, and traversal-free"
        )
    for part in path.parts:
        _validate_portable_segment(part, field=field)
    return path


def _validate_portable_segment(value: str, *, field: str) -> None:
    if value in {"", ".", ".."}:
        raise PathSafetyError(f"{field} contains an invalid path segment")
    if value.endswith((" ", ".")):
        raise PathSafetyError(
            f"{field} contains a segment ending with space or period"
        )
    if any(
        ord(character) < 32 or character in _PORTABLE_FORBIDDEN
        for character in value
    ):
        raise PathSafetyError(
            f"{field} contains a nonportable filename character"
        )
    stem = value.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED:
        raise PathSafetyError(f"{field} contains a reserved filename segment")


@dataclass(frozen=True)
class AuthorizedRoot:
    """A directory identity used for descriptor-confined filesystem access."""

    path: Path
    label: str
    device: int
    inode: int

    @classmethod
    def existing(cls, path: Path, *, label: str) -> AuthorizedRoot:
        """Bind an existing real directory as an authorized root."""
        supplied = path.expanduser()
        if supplied.is_symlink():
            raise PathSafetyError(f"{label} must not be a symlink")
        try:
            resolved = supplied.resolve(strict=True)
        except (FileNotFoundError, RuntimeError) as error:
            raise PathSafetyError(f"{label} does not exist") from error
        if not resolved.is_dir():
            raise PathSafetyError(f"{label} must be a directory")
        descriptor = _open_directory(resolved, label=label)
        try:
            metadata = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        return cls(
            path=resolved,
            label=label,
            device=metadata.st_dev,
            inode=metadata.st_ino,
        )

    @classmethod
    def create(cls, path: Path, *, label: str) -> AuthorizedRoot:
        """Create, then bind, a real authorized directory."""
        supplied = path.expanduser()
        if supplied.is_symlink():
            raise PathSafetyError(f"{label} must not be a symlink")
        try:
            supplied.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise PathSafetyError(f"cannot create {label}") from error
        return cls.existing(supplied, label=label)

    def child_path(self, relative: str | PurePosixPath) -> Path:
        """Render a validated child path for reporting only."""
        safe = validate_relative_path(relative)
        return self.path.joinpath(*safe.parts)

    def state(
        self,
        relative: str | PurePosixPath,
    ) -> Literal["missing", "regular", "directory"]:
        """Classify a confined child without following symlinks."""
        safe = validate_relative_path(relative)
        try:
            parent = self._open_parent(safe.parts[:-1])
        except FileNotFoundError:
            return "missing"
        try:
            try:
                metadata = os.stat(
                    safe.parts[-1], dir_fd=parent, follow_symlinks=False
                )
            except FileNotFoundError:
                return "missing"
            if stat.S_ISLNK(metadata.st_mode):
                raise PathSafetyError(
                    f"{self.label} child must not be a symlink: {safe}"
                )
            if stat.S_ISREG(metadata.st_mode):
                return "regular"
            if stat.S_ISDIR(metadata.st_mode):
                return "directory"
            raise PathSafetyError(
                f"{self.label} child is not a regular file or directory: {safe}"
            )
        finally:
            os.close(parent)

    def read_bytes(
        self,
        relative: str | PurePosixPath,
        *,
        max_bytes: int | None = None,
    ) -> bytes:
        """Read one regular file through no-follow directory descriptors."""
        safe = validate_relative_path(relative)
        parent = self._open_parent(safe.parts[:-1])
        descriptor = -1
        try:
            try:
                descriptor = os.open(safe.parts[-1], _FILE_FLAGS, dir_fd=parent)
            except OSError as error:
                _raise_path_error(
                    error,
                    f"cannot safely open {self.label} child: {safe}",
                )
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise PathSafetyError(
                    f"{self.label} child is not a regular file: {safe}"
                )
            if max_bytes is not None and (
                max_bytes < 0 or metadata.st_size > max_bytes
            ):
                raise PathSafetyError(
                    f"{self.label} child exceeds its byte limit: {safe}"
                )
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                data = stream.read(None if max_bytes is None else max_bytes + 1)
            if max_bytes is not None and len(data) > max_bytes:
                raise PathSafetyError(
                    f"{self.label} child exceeds its byte limit: {safe}"
                )
            return data
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(parent)

    def read_text(
        self,
        relative: str | PurePosixPath,
        *,
        encoding: str = "utf-8",
        max_bytes: int | None = None,
    ) -> str:
        """Read and decode one confined regular file."""
        return self.read_bytes(relative, max_bytes=max_bytes).decode(encoding)

    def iter_files(
        self,
        *,
        suffix: str,
        recursive: bool,
        reject_directories: bool = False,
    ) -> tuple[PurePosixPath, ...]:
        """List regular files deterministically without following symlinks."""
        root = self._open_root()
        try:
            found: list[PurePosixPath] = []
            self._walk(
                root,
                prefix=(),
                suffix=suffix,
                recursive=recursive,
                reject_directories=reject_directories,
                found=found,
            )
        finally:
            os.close(root)
        return tuple(sorted(found, key=lambda item: item.as_posix()))

    def create_directory(
        self,
        relative: str | PurePosixPath,
    ) -> AuthorizedRoot:
        """Create and bind one confined child directory."""
        safe = validate_relative_path(relative)
        parent = self._open_parent(safe.parts[:-1])
        child = -1
        try:
            os.mkdir(safe.parts[-1], mode=0o700, dir_fd=parent)
            child = os.open(safe.parts[-1], _DIRECTORY_FLAGS, dir_fd=parent)
            metadata = os.fstat(child)
            os.fsync(parent)
        except FileExistsError:
            raise FileExistsError(self.child_path(safe)) from None
        except OSError as error:
            _raise_path_error(
                error,
                f"cannot safely create {self.label} child directory: {safe}",
            )
        finally:
            if child >= 0:
                os.close(child)
            os.close(parent)
        return AuthorizedRoot(
            path=self.child_path(safe),
            label=f"{self.label} child {safe}",
            device=metadata.st_dev,
            inode=metadata.st_ino,
        )

    def rename_child(
        self,
        source: str | PurePosixPath,
        destination: str | PurePosixPath,
    ) -> Path:
        """Rename a confined child while refusing an existing destination."""
        safe_source = validate_relative_path(source, field="source")
        safe_destination = validate_relative_path(
            destination,
            field="destination",
        )
        if safe_source.parts[:-1] != safe_destination.parts[:-1]:
            raise PathSafetyError("rename source and destination must be peers")
        parent = self._open_parent(safe_source.parts[:-1])
        try:
            try:
                os.stat(
                    safe_destination.parts[-1],
                    dir_fd=parent,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(self.child_path(safe_destination))
            os.rename(
                safe_source.parts[-1],
                safe_destination.parts[-1],
                src_dir_fd=parent,
                dst_dir_fd=parent,
            )
            os.fsync(parent)
        finally:
            os.close(parent)
        return self.child_path(safe_destination)

    def write_bytes(
        self,
        relative: str | PurePosixPath,
        content: bytes,
        *,
        replace: bool,
    ) -> Path:
        """Atomically write one confined file without following symlinks."""
        safe = validate_relative_path(relative)
        parent = self._open_parent(safe.parts[:-1])
        leaf = safe.parts[-1]
        temporary = f".koios-{leaf}-{secrets.token_hex(12)}.tmp"
        descriptor = -1
        try:
            try:
                existing = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if stat.S_ISLNK(existing.st_mode):
                    raise PathSafetyError(
                        f"{self.label} destination must not be a symlink: "
                        f"{safe}"
                    )
                if not stat.S_ISREG(existing.st_mode):
                    raise PathSafetyError(
                        f"{self.label} destination is not a regular file: "
                        f"{safe}"
                    )
                if not replace:
                    raise FileExistsError(self.child_path(safe))
            descriptor = os.open(
                temporary,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=parent,
            )
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.close(descriptor)
            descriptor = -1
            if replace:
                os.replace(
                    temporary,
                    leaf,
                    src_dir_fd=parent,
                    dst_dir_fd=parent,
                )
            else:
                try:
                    os.link(
                        temporary,
                        leaf,
                        src_dir_fd=parent,
                        dst_dir_fd=parent,
                        follow_symlinks=False,
                    )
                except FileExistsError:
                    raise FileExistsError(self.child_path(safe)) from None
                finally:
                    os.unlink(temporary, dir_fd=parent)
            os.fsync(parent)
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
            raise
        finally:
            os.close(parent)
        return self.child_path(safe)

    def _open_root(self) -> int:
        descriptor = _open_directory(self.path, label=self.label)
        metadata = os.fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino) != (self.device, self.inode):
            os.close(descriptor)
            raise PathSafetyError(
                f"{self.label} changed after it was authorized"
            )
        return descriptor

    def _open_parent(self, parts: tuple[str, ...]) -> int:
        descriptor = self._open_root()
        try:
            for part in parts:
                try:
                    child = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
                except OSError as error:
                    _raise_path_error(
                        error,
                        f"{self.label} path contains a symlink or "
                        f"non-directory component: {part}",
                    )
                os.close(descriptor)
                descriptor = child
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def _walk(
        self,
        descriptor: int,
        *,
        prefix: tuple[str, ...],
        suffix: str,
        recursive: bool,
        reject_directories: bool,
        found: list[PurePosixPath],
    ) -> None:
        with os.scandir(descriptor) as entries:
            ordered = sorted(entries, key=lambda item: item.name)
        for entry in ordered:
            relative = PurePosixPath(*prefix, entry.name)
            if entry.is_symlink():
                raise PathSafetyError(
                    f"{self.label} contains a symlink: {relative}"
                )
            if entry.is_dir(follow_symlinks=False):
                if not recursive:
                    if reject_directories:
                        raise PathSafetyError(
                            f"{self.label} contains an unexpected directory: "
                            f"{relative}"
                        )
                    continue
                try:
                    child = os.open(
                        entry.name, _DIRECTORY_FLAGS, dir_fd=descriptor
                    )
                except OSError as error:
                    _raise_path_error(
                        error,
                        f"cannot safely traverse {self.label}: {relative}",
                    )
                try:
                    self._walk(
                        child,
                        prefix=(*prefix, entry.name),
                        suffix=suffix,
                        recursive=True,
                        reject_directories=reject_directories,
                        found=found,
                    )
                finally:
                    os.close(child)
                continue
            if entry.is_file(follow_symlinks=False):
                if entry.name.endswith(suffix):
                    found.append(relative)
                continue
            raise PathSafetyError(
                f"{self.label} contains an unsupported filesystem object: "
                f"{relative}"
            )


def read_path_bytes(
    path: Path,
    *,
    label: str,
    max_bytes: int | None = None,
) -> bytes:
    """Read an explicit file through an authorized parent directory."""
    root = AuthorizedRoot.existing(
        path.expanduser().parent, label=f"{label} parent"
    )
    return root.read_bytes(path.name, max_bytes=max_bytes)


def read_path_text(
    path: Path,
    *,
    label: str,
    encoding: str = "utf-8",
    max_bytes: int | None = None,
) -> str:
    """Read and decode an explicit file without following symlinks."""
    return read_path_bytes(path, label=label, max_bytes=max_bytes).decode(
        encoding
    )


def write_path_bytes(
    path: Path,
    content: bytes,
    *,
    label: str,
    replace: bool,
) -> Path:
    """Atomically write an explicit file through its authorized parent."""
    root = AuthorizedRoot.create(
        path.expanduser().parent, label=f"{label} parent"
    )
    return root.write_bytes(path.name, content, replace=replace)


def assert_safe_explicit_path(path: Path, *, label: str) -> Path:
    """Validate a missing or regular explicit path for an external library."""
    root = AuthorizedRoot.existing(
        path.expanduser().parent, label=f"{label} parent"
    )
    state = root.state(path.name)
    if state not in {"missing", "regular"}:
        raise PathSafetyError(f"{label} must be a regular file or missing")
    return root.child_path(path.name)


def _open_directory(path: Path, *, label: str) -> int:
    try:
        descriptor = os.open(path, _DIRECTORY_FLAGS)
    except OSError as error:
        _raise_path_error(error, f"cannot safely open {label}")
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        raise PathSafetyError(f"{label} must be a directory")
    return descriptor


def _raise_path_error(error: OSError, message: str) -> Never:
    if error.errno in {errno.ELOOP, errno.ENOTDIR}:
        raise PathSafetyError(message) from error
    raise error
