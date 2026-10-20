"""Write files so a crash or power cut leaves the old file or the new one, never half of one.

Memories are the thing Engram exists to keep, so every file that holds one is
written to a temporary file in the same folder, flushed to disk, and then
renamed over the target. A rename is all-or-nothing on the filesystems Engram
runs on, so readers never see a truncated file.
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
        with open(tmp, "w", encoding="utf-8") as fh:
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
