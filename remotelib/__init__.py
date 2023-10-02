"""RemotePath library"""

__all__ = ("Host", "Local", "Path", "Remote", "split")

from ._file import Path, split
from ._ssh import Host, Local, Remote
