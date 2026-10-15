"""A best-effort local wake signal for the durable database worker.

The web process and ``runworker`` intentionally share a persistent volume in the
single-container deployment.  A small atomically replaced file gives the web
process a cheap way to wake an otherwise idle worker without keeping a database
connection or a PostgreSQL listener alive.  The database queue remains the
source of truth: a missing signal only delays work until the fallback poll.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import time
import uuid

from django.conf import settings
from django.db import transaction


def _wake_path() -> Path:
    """Return the shared-volume signal path, with an explicit deployment override."""
    configured = os.getenv("WORKER_WAKE_FILE", "").strip()
    if configured:
        return Path(configured)
    return Path(settings.MEDIA_ROOT) / ".imc-worker-wake"


class WorkerWake:
    """Observe and update the local worker wake file without touching the DB."""

    def __init__(self, path: Path | None = None):
        self.path = path or _wake_path()

    def token(self):
        """An opaque value which changes whenever a successful signal is written."""
        try:
            stat = self.path.stat()
        except OSError:
            return None
        return stat.st_ino, stat.st_mtime_ns, stat.st_size

    def signal(self) -> bool:
        """Atomically signal a worker. Failure is safe because polling remains."""
        temporary = None
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".imc-worker-wake-", dir=self.path.parent)
            with os.fdopen(descriptor, "w", encoding="ascii") as stream:
                stream.write(f"{time.time_ns()}-{uuid.uuid4().hex}\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            temporary = None
            return True
        except OSError:
            # Do not turn a successfully committed user request into an error
            # merely because the optional local signalling channel is absent.
            return False
        finally:
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def wait_for_change(self, token, timeout: float, *, check_interval: float = 0.5, stopping=None) -> bool:
        """Wait locally until a signal arrives or fallback polling is due.

        ``check_interval`` is deliberately capped by the caller at one second,
        so web-created work is observed promptly without querying PostgreSQL.
        """
        deadline = time.monotonic() + max(0, timeout)
        interval = max(0.05, check_interval)
        while True:
            if self.token() != token:
                return True
            if stopping and stopping():
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self.token() != token
            time.sleep(min(interval, remaining))


def wake_worker_after_commit() -> None:
    """Signal only after the queue row is durable and visible to the worker."""
    transaction.on_commit(WorkerWake().signal)
