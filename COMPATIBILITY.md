# Compatibility

**Version:** 0.1.0

## Python

| Runtime | Status in v0.1.0 | How it was checked |
|---|---|---|
| CPython **3.6.15** (conda-forge build, modern Linux) | **Full test suite executed and passed** (see CHANGELOG / PR for counts) | `python3.6 -m unittest discover -s tests -t .` |
| CPython 3.11 / 3.12 / 3.13 | Full test suite executed and passed | same command |
| Python 3.6 on a real **RHEL/CentOS 7** host | **NOT verified** | needs a run on the target server (`tools/preflight.py`, then the test suite) |
| Python 2.x, Python < 3.6 | Not supported | |

What that means: the code is proven to run on a real Python 3.6 interpreter, but not yet on the production
operating system. CentOS 7 differs from the test machine in glibc, filesystem type and the way Python 3.6 was
packaged. Do not treat v0.1.0 as production-verified until `tools/preflight.py` and the tests pass **on the server**.

Python 3.6 rules followed: no `dataclasses`, `contextvars`, `datetime.fromisoformat`, `zoneinfo`,
`subprocess.run(capture_output=...)`, walrus operator, positional-only parameters or `from __future__ import annotations`.
`tests/test_version.py` additionally parses every file with `ast.parse(..., feature_version=(3, 6))` (Python 3.8+ only).

## CentOS 7 / deployment

- No root, no `sudo`, no `pip install`, no change to system Python: copy the `truecorp_core/` directory and set `PYTHONPATH`.
- Standard library only: `os, sys, re, json, gzip, zlib, time, stat, errno, logging, threading, datetime, contextlib, fcntl`.
- No Docker, Redis, database table or external logging service.
- Linux only for full behaviour. `fcntl` (flock) is POSIX; on Windows the library imports and runs but has **no
  cross-process locking** (development machines only).

## Known limitations

1. **Local filesystem only.** `flock` and `O_APPEND` semantics are not guaranteed on NFS/CIFS. Put `logs/` on a local disk.
2. **Compression runs in the thread that triggered rotation.** A very large log pauses that call (seconds for hundreds of MB).
3. **Late-writer window.** A process that opened the old file just before another process rotated it could append
   after the archive was verified. The size re-check and per-write inode check shrink this window to microseconds;
   they cannot remove it. Records written in that window can be lost.
4. **Very long records.** A record is normally one `write()` call and therefore not interleaved with other processes;
   this is not guaranteed for records larger than ~8 KB (long tracebacks).
5. **Redaction is best effort** (see README "Security"). It is not a guarantee that no secret reaches the log.
6. **Archive date range is the calendar period**, not the first/last record. If rotation was delayed (failure, process
   not running) records after the period end can sit inside an archive whose name ends earlier.
7. **Rotation is checked when a record is written** and at startup. A process that never logs does not rotate; the next
   start (or `cleanup_logs()`) catches up. Retention also needs a start or a call.
8. **Time zone is fixed to UTC+7** (Asia/Bangkok has no DST). Timestamps have no offset in the line, by design of the format.
9. **Config changes take effect on the next `setup_logging()`** with the new values replacing the old handlers; a changed
   `interval_days` applies from the stored period start without an immediate rotation unless a boundary has passed.
10. `allowed_roots`/protected directories are validated with `realpath` at setup time only.

## Multi-process restrictions

- Several processes may append to the **same** active file (each line is one `write` on an `O_APPEND` descriptor).
- Rotation, recovery and retention are serialized by a non-blocking `flock` on `.logging_state/<name>.lock`. A process
  that cannot get the lock skips that step and tries again after 60 seconds; it never waits. The kernel releases the lock
  if its owner dies, so there are no stale locks and the lock file is never deleted.
- Every process checks, before each write, that its file descriptor still points to the active path and reopens it if
  another process rotated the file.
- `threading.Lock` is **not** used for cross-process safety; handler locks only protect threads inside one process.
- Recommended: give jobs that can overlap and must stay separable their own `filename`.
- Two applications must not share the same `directory` **and** `filename`.
