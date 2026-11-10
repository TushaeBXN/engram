"""One writer at a time for an index folder, across threads *and* processes.

Several Engram processes usually share one index: the MCP server, the
auto-recall hook, the save hook and ``engram mine`` can all be running at
once. ChromaDB's local store is not built for that; a write interrupted or
interleaved by another process can leave its HNSW index unreadable. A
:class:`StoreLock` makes every process take turns:

* a ``threading.Lock`` serialises threads inside one process (the Rust
  bindings release the GIL, so the GIL does not protect them);
* an advisory file lock (``flock``) on a lock file inside the index folder
  serialises processes. Reads take it shared, writes exclusive.

The file lock is released by the operating system when a process dies, so a
crash never leaves the index locked. If the lock cannot be taken within
*timeout* seconds the operation goes ahead anyway (as it always did before
this lock existed) and says so once on stderr: a slow answer is better than
a hung hook. Where ``flock`` does not exist (Windows) only the thread lock
applies.
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None  # type: ignore[assignment]

DEFAULT_TIMEOUT = 30.0
_POLL = 0.05


class StoreLock:
    """``with lock:`` for a write, ``with lock.shared():`` for a read."""

    def __init__(self, path, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.path = Path(path)
        self.timeout = timeout
        self._thread = threading.Lock()
        self._fd: int | None = None
        self._warned = False
        self._exclusive = contextlib.ExitStack()  # the exit of the current ``with lock:``

    # -- file lock --------------------------------------------------------

    def _open(self) -> int | None:
        if self._fd is None and fcntl is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
            except OSError:
                return None
        return self._fd

    def _flock(self, exclusive: bool) -> bool:
        fd = self._open()
        if fd is None:
            return False
        mode = (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(fd, mode)
                return True
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    if not self._warned:
                        self._warned = True
                        print(f"engram: another Engram process has held the index lock for over "
                              f"{self.timeout:.0f}s; continuing without it ({self.path})", file=sys.stderr)
                    return False
                time.sleep(_POLL)
            except OSError:  # a filesystem without flock (some network mounts)
                return False

    @contextlib.contextmanager
    def _hold(self, exclusive: bool):
        with self._thread:
            locked = self._flock(exclusive)
            try:
                yield
            finally:
                if locked:
                    with contextlib.suppress(OSError):
                        fcntl.flock(self._fd, fcntl.LOCK_UN)

    # -- public -----------------------------------------------------------

    def shared(self):
        """Hold the lock for a read: other readers may run, writers wait."""
        return self._hold(False)

    def exclusive(self):
        """Hold the lock for a write: everyone else waits."""
        return self._hold(True)

    def __enter__(self):
        cm = self._hold(True)
        cm.__enter__()
        self._exclusive.push(cm.__exit__)
        return self

    def __exit__(self, *exc):
        return self._exclusive.__exit__(*exc)

    def close(self) -> None:
        if self._fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._fd)
            self._fd = None
