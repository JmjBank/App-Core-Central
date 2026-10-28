"""Thread-local run context for correlation fields."""

from __future__ import unicode_literals

import threading

_local = threading.local()

# Reserved keys merged into every log record when present.
CONTEXT_KEYS = (
    "run_id",
    "tracking_id",
    "async_id",
    "batch_id",
    "event",
    "step",
    "duration_ms",
    "hostname",
    "pid",
)


def _get_store():
    store = getattr(_local, "context", None)
    if store is None:
        store = {}
        _local.context = store
    return store


def set_run_context(run_id=None, **fields):
    """Set correlation context for the current thread."""
    store = _get_store()
    store.clear()
    if run_id is not None:
        store["run_id"] = run_id
    for key, value in fields.items():
        if key in CONTEXT_KEYS or key.startswith("_"):
            store[key] = value
        else:
            store[key] = value


def get_run_context():
    store = getattr(_local, "context", None)
    if not store:
        return {}
    return dict(store)


def clear_run_context():
    store = getattr(_local, "context", None)
    if store is not None:
        store.clear()
    if hasattr(_local, "context"):
        del _local.context


class ContextFilter(object):
    """Inject thread-local context into each LogRecord."""

    def filter(self, record):
        ctx = get_run_context()
        for key in CONTEXT_KEYS:
            setattr(record, key, ctx.get(key))
        extra_keys = set(ctx.keys()) - set(CONTEXT_KEYS)
        for key in extra_keys:
            setattr(record, key, ctx.get(key))
        return True
