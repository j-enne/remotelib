"""Unit tests for the remotelib.Path object."""
# pylint: disable=protected-access

from pathlib import Path as LocalPath

from remotelib import Host, Local, Path, Remote


def test_creation() -> None:
    """Test the initialisation of different path names."""

    def _check(
        path_in: str, path_out: str | None = None, host: Host | None = None
    ) -> None:
        """Assert the underlying private structures for input strings."""
        if path_out is None:
            path_out = path_in
        if host is None:
            host = Local()

        path = Path(path_in)
        assert path._path == LocalPath(path_out)
        assert path._host == host

    _check("/foo/bar")
    _check("foo/bar")
    _check("~/foo/bar")
    _check("~me/foo/bar")
    _check("/x@foo/bar")
    _check("/fo:o/bar")
    _check("abc:def")
    _check("there:/foo", "/foo", Remote("there"))
    _check("me@there:/fo:o/bar", "/fo:o/bar", Remote("there", user="me"))
    _check("me@there:60:~", "~", Remote("there", user="me", port=60))
    _check("there:/60:x", "/60:x", Remote("there"))
    _check("name@a:~name/.config", "~name/.config", Remote("a", user="name"))
    _check("1:2:/3", "/3", Remote("1", port=2))

    # check default and non-string init.
    assert Path()._path == LocalPath()
    assert Path()._host == Local()

    assert Path(LocalPath("a/b"))._path == LocalPath("a/b")
    assert Path(LocalPath("a/b"))._host == Local()

    assert Path(Path("a:/b"))._path == LocalPath("/b")
    assert Path(Path("a:/b"))._host == Remote("a")


def test_properties() -> None:
    """Test the exposed Path properties."""
    assert Path("foo:/bar").remote == "foo"
    assert Path("a@foo:/bar").remote == "a@foo"
    assert Path("a@foo:1:/bar").remote == "a@foo:1"

    assert Path("a@foo:/bar/foo").parent == Path("a@foo:/bar")
    assert Path("a@foo:~bar/foo").parent == Path("a@foo:~bar")

    assert Path("a@foo:/bar/foo").is_remote
    assert not Path("~bar/foo").is_remote


def test_dunder() -> None:
    """Test the internal __foo__ methods."""
    assert str(Path("a@b:123:~/xyz")) == "a@b:123:~/xyz"

    assert Path("abc/def.g") == Path("abc/def.g")
    assert Path("a@x:abc/def.g") == Path("a@x:abc/def.g")
    assert Path("abc/def.g") != Path("def/abc.g")
    assert Path("x:abc/def.g") != Path("abc/def.g")
    # Equality with pathlib
    assert Path("abc/def.g") == LocalPath("abc/def.g")
    assert Path("x:abc/def.g") != LocalPath("abc/def.g")


def test_join() -> None:
    """Test the joining of paths and paths/strings."""
    assert Path("a:/b") / "c" == Path("a:/b/c")
