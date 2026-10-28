"""Per-thread run context (run_id + business fields such as tracking_id).

Behaviour, by design:
* Thread-local: a thread sees only the context it set itself. New threads start empty
  (nothing is inherited), so one job/tracking id can never leak into another thread.
  Worker threads must call ``set_run_context`` themselves.
* Per process: processes never share context.
* ``set_run_context`` REPLACES the whole context (fields from the previous job are
  dropped, not merged). Use the ``run_context`` manager to scope a tracking id and
  restore the outer context afterwards.
(contextvars is not used because it does not exist in Python 3.6.)
"""
import re
import threading
from contextlib import contextmanager

_local = threading.local()
_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _build(run_id, fields):
    if run_id is None or str(run_id) == "":
        raise ValueError("run_id is required")
    for name in fields:
        if not _FIELD.match(name):
            raise ValueError("invalid context field name %r" % (name,))
    ctx = dict(fields)
    ctx["run_id"] = str(run_id)
    return ctx


def set_run_context(run_id, **fields):
    _local.ctx = _build(run_id, fields)


def get_run_context():
    return dict(getattr(_local, "ctx", None) or {})


def clear_run_context():
    _local.ctx = {}


@contextmanager
def run_context(run_id, **fields):
    previous = get_run_context()
    set_run_context(run_id, **fields)
    try:
        yield
    finally:
        _local.ctx = previous
