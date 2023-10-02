"""Things accessible over SSH and methods of interacting with them."""

from __future__ import annotations

__all__ = ("Host", "Local", "Remote")

import contextlib
import logging
import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import Iterator, Protocol

log = logging.getLogger("remotelib")
_NewException = type[Exception] | dict[str, type[Exception]] | None


_OPTS = " ".join(
    (
        "-o StrictHostKeyChecking=no",
        "-o UserKnownHostsFile=/dev/null",
        "-o LogLevel=ERROR",
        "-o PasswordAuthentication=no",
    )
)

_DEFAULT_USER = os.getlogin()
_DEFAULT_PORT = 22

_DEFAULT_BASH_EXCEPTIONS = {
    "No such file or directory": FileNotFoundError,
    "Permission denied": PermissionError,
    "File exists": FileExistsError,
}


@contextlib.contextmanager
def _wrap_exception(exc: _NewException) -> Iterator[None]:
    """Wrap a call to convert process errors into python builtins."""
    try:
        yield
    except subprocess.CalledProcessError as process_err:
        new_exc: Exception = process_err  # defaults to same

        if isinstance(exc, dict) or not exc:
            exc = _DEFAULT_BASH_EXCEPTIONS | (exc or {})  # type: ignore
            for key, exception in exc.items():
                if key in process_err.stderr:
                    new_exc = exception(process_err.stderr)
        elif exc:
            new_exc = exc(process_err.stderr)

        raise new_exc from process_err


def _run(cmd: str, *, timeout: float | None = None) -> str:
    """Run, capture and check a command in a shell-like way."""
    log.debug("Running: %s", cmd)
    return subprocess.check_output(
        cmd, shell=True, text=True, stderr=subprocess.PIPE, timeout=timeout
    ).strip()


def _ssh_run(
    cmd: str,
    address: str,
    port: int = _DEFAULT_PORT,
    timeout: int | None = None,
) -> str:
    """Run a command over ssh using an address ([user@]hostname).

    By default times out after 5 seconds."""
    return _run(
        f"ssh {_OPTS} -p {port} {address} {shlex.quote(cmd)}",
        timeout=timeout or 5,
    )


class Host(Protocol):
    """Required attributes and methods for a host machine."""

    @property
    def prefix(self) -> str:
        """The prefix that should be added to a path to fully describe it.

        Local:
            /foo -> /foo
        Remote:
            /foo -> me@there:8000:/foo
                    ^^^^^^^^^^^^^^
        """

    @property
    def is_remote(self) -> bool:
        """True if host is remote, False if it is the localhost."""

    def run(
        self,
        cmd: str,
        exc: _NewException = None,
        *,
        timeout: int | None = None,
    ) -> str:
        """Method of running a shell command and returning text."""


@dataclass
class Local:
    """The local host."""

    @property
    def is_remote(self) -> bool:
        """Local is not remote"""
        return False

    @property
    def prefix(self) -> str:
        """No local prefix."""
        return ""

    def run(
        self,
        cmd: str,
        exc: _NewException = None,
        *,
        timeout: int | None = None,
    ) -> str:
        """Run and capture a command on a host."""
        with _wrap_exception(exc):
            return _run(cmd, timeout=timeout)


@dataclass
class Remote:
    """SSH-able host machine constructed from SSH details

    Provides a method for executing shell commands remotely.
    """

    hostname: str
    user: str = _DEFAULT_USER
    port: int = _DEFAULT_PORT

    @property
    def is_remote(self) -> bool:
        """Remote object is remote"""
        return True

    @property
    def prefix(self) -> str:
        """The remote prefix ending in a colon."""
        # Relies on implementation of __repr__
        return f"{self}:"

    def __str__(self) -> str:
        """Describe the host with a simple string - excluding defaults."""
        description = self.hostname
        if self.user != _DEFAULT_USER:
            description = f"{self.user}@{description}"
        if self.port != _DEFAULT_PORT:
            description = f"{description}:{self.port}"
        return description

    def __repr__(self) -> str:
        """Represent the host object with a simple string - excluding defaults."""
        return f"{self.__class__.__name__}('{self}')"

    @classmethod
    def from_str(cls, host: str) -> Remote:
        """From a string [<user>@]<hostname>[:<port>]"""
        if ":" in host:
            assert host.count(":") == 1
            host, port_ = host.split(":")
            port = int(port_)
        else:
            port = _DEFAULT_PORT

        if "@" in host:
            assert host.count("@") == 1
            user, host = host.split("@")
        else:
            user = _DEFAULT_USER

        return cls(hostname=host, user=user, port=port)

    def run(
        self,
        cmd: str,
        exc: _NewException = None,
        *,
        timeout: int | None = None,
    ) -> str:
        """Run and capture a command on a host.

        If the command on the host fails then optionally wrap the stderr in
        the passed exception class.
        """
        with _wrap_exception(exc):
            return _ssh_run(
                cmd,
                address=f"{self.user}@{self.hostname}",
                port=self.port,
                timeout=timeout,
            )
