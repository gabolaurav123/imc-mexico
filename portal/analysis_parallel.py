"""One reserved, independent reference lookup alongside technical research."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from django.db import connections


class ConcurrentReference:
    """Keep cancellation, database connections and usage local to one branch.

    Admission and identity checks belong to the caller. Even when the other
    branch fails, settle waits for the bounded request and accounts for it.
    No background work or database connection survives the analysis attempt.
    """

    def __init__(self, call):
        self.stopped = Event()
        self._accounted = False
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="imc-reference")
        self._future = self._pool.submit(self._run, call)

    def _run(self, call):
        try:
            return call(self.stopped)
        except Exception:
            self.stopped.set()
            raise
        finally:
            # Django connections are thread-local. Only this worker's own
            # connection is closed; the main transaction is never shared.
            connections.close_all()

    def settle(self, usage, *, raise_error=True):
        error = None
        try:
            value, branch_usage = self._future.result()
        except Exception as exc:
            value, branch_usage, error = None, getattr(exc, "accounted_usage", None), exc
        if not self._accounted:
            usage.add(branch_usage)
            usage.estimated_tokens += getattr(branch_usage, "estimated_tokens", 0)
            usage.web_search_calls += getattr(branch_usage, "web_search_calls", 0)
            self._accounted = True
        if error is not None and raise_error:
            raise error
        return value

    def close(self):
        self.stopped.set()
        self._pool.shutdown(wait=True)
