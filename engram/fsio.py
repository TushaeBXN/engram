"""Write files so a crash or power cut leaves the old file or the new one, never half of one.

Memories are the thing Engram exists to keep, so every file that holds one is
written to a temporary file in the same folder, flushed to disk, and then
renamed over the target. A rename is all-or-nothing on the filesystems Engram
runs on, so readers never see a truncated file. Files are created readable by
their owner only.
"""

from __future__ import annotations

import os
from pathlib import Path

TMP_SUFFIX = ".tmp"


def atomic_write_text(path, text: str) -> None:
    """Replace *path* with *text* atomically (the folder must exist)."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}{TMP_SUFFIX}")
    try:
        # Mode 0600: memories are private, whatever the folder above allows.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def make_private(folder) -> None:
    """Make *folder* accessible to its owner only (0700), if it is ours and isn't already.

    Other accounts on the same computer then cannot list or read anything
    beneath it. Does nothing on Windows, or when the folder belongs to
    someone else.
    """
    if os.name != "posix":
        return
    try:
        st = os.stat(folder)
        if st.st_uid == os.getuid() and st.st_mode & 0o077:
            os.chmod(folder, st.st_mode & 0o7700)
    except OSError:
        pass
