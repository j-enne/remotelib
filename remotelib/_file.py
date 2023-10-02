"""
File-related operations.

Re-implement `pathlib` with the possibility of executing the action on a remote
host.

Definitions:
    remote: a string of '<user>@<hostname>:<port>' where user and port are
            optional.
"""
# pylint: disable=protected-access,too-many-public-methods

from __future__ import annotations

__all__ = ("Path", "split", "tmp_path")

import contextlib
import os
import tempfile
from pathlib import Path as LocalPath
from stat import S_ISDIR, S_ISLNK, S_ISREG, S_ISSOCK
from typing import Generator, Iterable, Iterator

from ._ssh import Host, Local, Remote


def split(path: str) -> tuple[Host, LocalPath]:
    """Split a path string into a host (local/remote) and pathlib Path.

    So 'server:/bin/sh' becomes:
        Remote('server'), pathlib.Path('/bin/sh')
    """
    host: Host
    if ":/" in path and path.index(":") < path.index("/"):
        address, path = path.split(":/", maxsplit=1)
        path = "/" + path
        host = Remote.from_str(address)
    elif ":~" in path and path.index(":") < path.index("~"):
        address, path = path.split(":~", maxsplit=1)
        path = "~" + path
        host = Remote.from_str(address)
    else:
        host = Local()

    return host, LocalPath(path)


class Path:
    """Representation of a path on a host."""

    _path: LocalPath
    _host: Host

    def __init__(self, path: str | Path | LocalPath = ".") -> None:
        """Create a local/remote path representation.

        Local paths look like:
            foo/bar.py
            /path/to/here

        Remote paths look like:
            my-server:/path/to/here
            me@pypi.org:~/.config/mypy
            root@localhost:8080:/etc/config

        A remote path is defined by a colon (:) appearing just before the first
        slash (/) or tilde (~).

        NOTE: no relative remote paths. immutable.
        """
        match path:
            case str():
                self._host, self._path = split(path)
            case LocalPath():
                self._host, self._path = Local(), path
            case Path():
                # are these copies/mutable?
                self._host, self._path = path._host, path._path
            case _:
                raise TypeError(
                    f"expected str, pathlib.Path or remotelib.Path, not {type(path).__name__}"
                )

    # internal methods
    def __str__(self) -> str:
        """String form is '<host details>:<path>'."""
        return self._host.prefix + str(self._path)

    def __repr__(self) -> str:
        """Representation of a 'Path' object."""
        return f"{self.__class__.__name__}('{self}')"

    def __eq__(self, other: object) -> bool:
        """True if the other 'thing' refers to the same underlying path."""
        if isinstance(other, Path):
            return self._path == other._path and self._host == other._host
        elif isinstance(other, LocalPath):
            return self._path == other and not self.is_remote
        else:
            return False

    def _add_remote(self, path: str | LocalPath) -> Path:
        """Add the current remote prefix (see defn.) to a path to create a remotelib Path."""
        return type(self)(self._host.prefix + str(path))

    # methods wrapping pathlib.Path
    @property
    def name(self) -> str:
        """The name of the underlying file path."""
        return self._path.name

    @property
    def parent(self) -> Path:
        """True if the path is on a remote host."""
        return self._add_remote(self._path.parent)

    @property
    def parts(self) -> tuple[str, ...]:
        """The parts of the underlying path (ignores the host)."""
        return self._path.parts

    @property
    def suffix(self) -> str:
        """
        The final component's last suffix, if any.

        This includes the leading period. For example: '.txt'
        """
        return self._path.suffix

    @property
    def suffixes(self) -> list[str]:
        """
        A list of the final component's suffixes, if any.

        These include the leading periods. For example: ['.tar', '.gz']
        """
        return self._path.suffixes

    @property
    def stem(self) -> str:
        """The final path component, minus its last suffix."""
        return self._path.stem

    def with_name(self, name: str) -> Path:
        """Return a new path with the file name changed."""
        return self._add_remote(self._path.with_name(name))

    def with_stem(self, stem: str) -> Path:
        """Return a new path with the stem changed."""
        return self._add_remote(self._path.with_stem(stem))

    def with_suffix(self, suffix: str) -> Path:
        """Return a new path with the file suffix changed.  If the path
        has no suffix, add given suffix.  If the given suffix is an empty
        string, remove the suffix from the path.
        """
        return self._add_remote(self._path.with_suffix(suffix))

    def is_absolute(self) -> bool:
        """True if the path is absolute (has both a root and, if applicable,
        a drive)."""
        return self._path.is_absolute()

    def relative_to(self, other_: str | Path | LocalPath) -> Path:
        """Return the relative path to another path identified by the passed
        arguments.  If the operation is not possible (because this is not
        a subpath of the other path, or the hosts don't match), raise ValueError.
        """
        other = Path(other_)
        if self._host != other._host:
            raise ValueError("hosts must match")
        return self._add_remote(self._path.relative_to(other._path))

    def is_relative_to(self, other_: str | Path | LocalPath) -> bool:
        """Return True if the path is relative to another path or False."""
        other = Path(other_)
        if self._host != other._host:
            return False
        return self._path.is_relative_to(other._path)

    def rename(self, target: str | Path | LocalPath) -> None:
        """Rename a path."""
        self.replace(target)

    def replace(self, target_: str | Path | LocalPath) -> None:
        """Replace a path (move with possible overwrites)."""
        target = Path(target_)

        if self.is_remote or target.is_remote:
            self.move_to(target, overwrite=True)
        else:
            # use the pathlib method if both local
            self._path.replace(target._path)

    def __truediv__(self, key: str | Path | LocalPath) -> Path:
        """
        Allow HostPath("foo") / "bar".

        NOTE: joining absolute paths wipes the first path:

            >>> Path("/a") / Path("/b")
            Path('/b')
        """
        if isinstance(key, Path):
            if self._host != key._host:
                raise ValueError("Hosts must be the same when joining paths")

        return self._add_remote(self._path / Path(key)._path)

    def exists(self) -> bool:
        """Host-agnostic implementation of pathlib.Path.exists()."""
        if self.is_remote:
            return self._host.run(f"[[ -f {self._path} ]] || echo no") != "no"
        else:
            return self._path.exists()

    def write_bytes(self, data: bytes) -> None:
        """Host-agnostic implementation of pathlib.Path.write_bytes()."""
        if self.is_remote:
            with tmp_path() as tmp:
                tmp._path.write_bytes(data)
                tmp.copy_to(self)  # copy because deleted by ctx mgr
        else:
            self._path.write_bytes(data)

    def read_bytes(self) -> bytes:
        """Host-agnostic implementation of pathlib.Path.read_text()."""
        if self.is_remote:
            with tmp_path() as tmp:
                self.copy_to(tmp)
                return tmp._path.read_bytes()  # read a local copy
        else:
            return (
                self._path.read_bytes()  # pylint: disable=unspecified-encoding
            )

    def write_text(self, data: str) -> None:
        """Host-agnostic implementation of pathlib.Path.write_text()."""
        if self.is_remote:
            with tmp_path() as tmp:
                tmp._path.write_text(  # pylint: disable=unspecified-encoding
                    data
                )
                tmp.copy_to(self)  # copy because deleted by ctx mgr
        else:
            self._path.write_text(data)  # pylint: disable=unspecified-encoding

    def read_text(self) -> str:
        """Host-agnostic implementation of pathlib.Path.read_text()."""
        if self.is_remote:
            return self._host.run(f"cat {self._path}")
        else:
            return (
                self._path.read_text()  # pylint: disable=unspecified-encoding
            )

    def mkdir(self, *, exist_ok: bool = False, parents: bool = False) -> None:
        """Host-agnostic implementation of pathlib.Path.mkdir()."""
        if self.is_remote:
            args = ""
            prefix = ""
            if parents:
                args += "-p"
            if exist_ok:
                prefix = f"[[ -f {self._path} ]] || "
            self._host.run(
                f"{prefix}mkdir {args} {self._path}",
            )
        else:
            self._path.mkdir(exist_ok=exist_ok, parents=parents)

    def symlink_to(self, real_file: Path) -> None:
        """Host-agnostic implementation of pathlib.Path.symlink_to()."""
        if self.is_remote:
            self._host.run(f"ln -s {real_file} {self._path}")
        else:
            self._path.symlink_to(real_file._path)

    def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
        """Host-agnostic implementation of pathlib.Path.stat()

        Works on linux, follows symlinks to stat the pointed to file by default.
        """
        if self.is_remote:
            if follow_symlinks:
                args = "-L"
            else:
                args = ""
            # 'mode %f ino %i dev %d nlink %h uid %u gid %g size %s atime %X mtime %Y ctime %W'
            mode_hex, *others = self._host.run(
                f"stat {args} --format='%f %i %d %h %u %g %s %X %Y %W' {self._path}"
            ).split()
            return os.stat_result(
                (int(mode_hex, 16), *(int(st) for st in others))
            )
        else:
            return self._path.stat(follow_symlinks=follow_symlinks)

    def lstat(self) -> os.stat_result:
        """Host-agnostic implementation of pathlib.Path.lstat()."""
        return self.stat(follow_symlinks=False)

    def unlink(self, *, missing_ok: bool = False) -> None:
        """Host-agnostic implementation of pathlib.Path.unlink()."""
        if self.is_remote:
            self._host.run(f"rm {'-f' if missing_ok else ''} {self._path}")
        else:
            self._path.unlink(missing_ok=missing_ok)

    def touch(self) -> None:
        """Host-agnostic implementation of pathlib.Path.touch()."""
        if self.is_remote:
            self._host.run(f"touch {self._path}")
        else:
            self._path.touch()

    def chmod(self, mode: int) -> None:
        """Host-agnostic implementation of pathlib.Path.chmod()."""
        if self.is_remote:
            # Covert the mode integer to octal and prefix with
            self._host.run(f"chmod {mode:o} {self._path}")
        else:
            self._path.chmod(mode)

    def resolve(self) -> Path:
        """Host-agnostic implementation of pathlib.Path.resolve()."""
        path: str | LocalPath
        if self.is_remote:
            path = self._host.run(
                f"realpath {self._path} || echo {self._path}"
            )
        else:
            path = self._path.resolve()
        return self._add_remote(path)

    def is_dir(self) -> bool:
        """Host-agnostic implementation of pathlib.Path.is_dir()."""
        return S_ISDIR(self.stat().st_mode)

    def is_file(self) -> bool:
        """Host-agnostic implementation of pathlib.Path.is_dir()."""
        return S_ISREG(self.stat().st_mode)

    def is_symlink(self) -> bool:
        """Host-agnostic implementation of pathlib.Path.is_dir()."""
        return S_ISLNK(self.stat().st_mode)

    def is_socket(self) -> bool:
        """Host-agnostic implementation of pathlib.Path.is_dir()."""
        return S_ISSOCK(self.stat().st_mode)

    def glob(self, glob_pattern: str) -> Generator[Path, None, None]:
        """Host-agnostic implementation of pathlib.Path.glob()."""
        files: Iterable[str | LocalPath]
        if self.is_remote:
            files = self._host.run(
                f"shopt -s extglob && ls -d {self._path}/{glob_pattern} || true"
            ).splitlines()
        else:
            files = self._path.glob(glob_pattern)

        yield from (self._add_remote(file) for file in files)

    # Non-pathlib - custom methods.
    @property
    def is_remote(self) -> bool:
        """True if the path is on a remote host."""
        return self._host.is_remote

    @property
    def remote(self) -> str | None:
        """Name of remote part of path or None if local."""
        if self.is_remote:
            return str(self._host)
        else:
            return None

    @property
    def rparts(self) -> tuple[str, str]:
        """Remote, path string tuple. Remote is an empty string if local."""
        return str(self._host), str(self._path)

    def copy_to(
        self, destination: Path, *, contents_only: bool = False
    ) -> None:
        """
        Copy any file/dir to any location regardless of host.

        contents_only: If self is a directory this will copy the contents of
        the directory to the location rather than the directory itself.
        """
        # NOTE: relies on the __str__ being what rsync expects.
        Local().run(  # run rsync locally!
            f"rsync -a {self}{'/' if contents_only else ''} {destination}",
            {"Read-only file system": PermissionError},
        )

    def move_to(
        self,
        destination: Path,
        *,
        contents_only: bool = False,
        overwrite: bool = True,
    ) -> None:
        """
        Move any file/dir to any location regardless of host.

        contents_only: If self is a directory this will copy the contents of
        the directory to the location rather than the directory itself.
        """
        args = "-a --remove-source-files"
        if not overwrite:
            # it is the rsync default
            args += " --ignore-existing"

        # NOTE: relies on the __str__ being what rsync expects.
        Local().run(  # run rsync locally!
            f"rsync {args} {self}{'/' if contents_only else ''} {destination}",
            {"Read-only file system": PermissionError},
        )


@contextlib.contextmanager
def tmp_path() -> Iterator[Path]:
    """Return a 'Path' to a unique local temporary file, cleaned up on exit."""
    with tempfile.NamedTemporaryFile() as f_:
        yield Path(f_.name)
