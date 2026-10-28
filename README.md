# TrueCorp-Python-Core

Shared Python library for TrueCorp enterprise applications. **Phase 1** delivers a portable **core logging** module built on the Python standard library only (no `pip install`, no root/sudo).

| Item | Value |
|------|--------|
| Current version | `0.1.0` (see [`VERSION`](VERSION)) |
| Target stable | `1.0.0` |
| Python | **3.6.x** (design target) |
| OS | RHEL/CentOS 7 (Linux) |

```python
from truecorp_core import __version__
from truecorp_core.logging import setup_logging, get_logger, set_run_context
```

---

## Portable installation (FTP/SFTP)

Deploy by copying the library directory next to your application (include the whole `truecorp_core/` tree; it contains a portable `VERSION` file synchronized with the repository root):

```text
APP_CANCEL_5534/
├── main.py
├── config.json
├── lib/
│   └── truecorp_core/          # includes VERSION for portable deployments
├── logs/
└── run.sh
```

### `PYTHONPATH` (Linux)

```bash
export PYTHONPATH="/path/to/APP_CANCEL_5534/lib:${PYTHONPATH}"
python3 main.py
```

Or in `run.sh`:

```bash
#!/bin/bash
APP_HOME="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="${APP_HOME}/lib:${PYTHONPATH}"
exec python3 "${APP_HOME}/main.py"
```

### Upload without breaking a running app

1. Upload the new library to a **staging** path, e.g. `lib/truecorp_core_0.1.0/`.
2. Run the **preflight** check (below) against the staging copy.
3. During an approved change window, rename:
   - `lib/truecorp_core` → `lib/truecorp_core_backup_<timestamp>`
   - `lib/truecorp_core_0.1.0` → `lib/truecorp_core`
4. Restart or allow the next cron execution to pick up the code (long-running daemons should restart after deploy).

### Rollback

```bash
cd /path/to/APP_CANCEL_5534/lib
rm -rf truecorp_core
mv truecorp_core_backup_<timestamp> truecorp_core
```

Verify:

```bash
PYTHONPATH="/path/to/APP_CANCEL_5534/lib" python3 -c "import truecorp_core; print(truecorp_core.__version__)"
```

### Read-only preflight (server)

```bash
export PYTHONPATH="/path/to/staging/lib:${PYTHONPATH}"
python3 - <<'PY'
import truecorp_core
from truecorp_core.logging.config import normalize_logging_config
print("version", truecorp_core.__version__)
normalize_logging_config({"directory": "./logs", "filename": "preflight.log"})
print("preflight_ok")
PY
```

Production deployment must follow your change-management and access-control procedures.

---

## Quick start

```python
import json
import os
from truecorp_core.logging import (
    setup_logging,
    get_logger,
    set_run_context,
    clear_run_context,
    shutdown_logging,
)

base_dir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(base_dir, "config.json"), encoding="utf-8") as f:
    config = json.load(f)

setup_logging(
    config["logging"],
    application_name=config["application"]["name"],
    environment=config["application"]["environment"],
    base_dir=base_dir,
)

set_run_context(run_id="RUN-20261028-001", tracking_id="ABC123")
logger = get_logger(config["application"]["name"])
logger.info("Application started")
logger.info("event=IOM_GET_SUCCESS duration_ms=%s", 1250)

clear_run_context()
shutdown_logging()
```

See [`examples/`](examples/) for cron and daemon samples.

---

## Logging API

| Function | Description |
|----------|-------------|
| `setup_logging(config, application_name=None, environment=None, base_dir=None)` | Validate config, attach handlers (idempotent for identical config). |
| `get_logger(name)` | Standard `logging.getLogger(name)` — full stdlib compatibility. |
| `set_run_context(run_id=None, **fields)` | Thread-local correlation fields for subsequent log lines. |
| `clear_run_context()` | Clear thread-local context. |
| `shutdown_logging()` | Flush/close TrueCorp handlers and reset setup state. |

### Default log line format (plain text)

```text
2026-10-28 15:00:01 [INFO] [APP_CANCEL_5534] [RUN-001] Application started
2026-10-28 15:00:02 [INFO] [APP_CANCEL_5534] [RUN-001] tracking_id=ABC123 event=IOM_GET_START
```

- Timestamp: **Asia/Bangkok** (fixed UTC+7, no DST).
- Missing run ID is shown as `[-]` (no formatter error).
- Optional context keys: `tracking_id`, `async_id`, `batch_id`, `event`, `step`, `duration_ms`, `hostname`, `pid`, plus custom fields (sanitized / redacted when enabled).

### Idempotent `setup_logging()`

- First call configures root handlers.
- Repeat calls with the **same** normalized config are no-ops (no duplicate handlers).
- Repeat calls with a **different** config emit `RuntimeWarning` and **keep** the original handlers (fail-safe for running processes).

---

## Configuration reference (`logging` section)

Application code may keep its existing top-level config; only the `logging` object is consumed by `setup_logging()`.

| Key | Type | Default | Validation / notes |
|-----|------|---------|-------------------|
| `enabled` | bool | `true` | If `false`, setup marks configured but adds no handlers. |
| `level` | string | `INFO` | One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `directory` | string | `./logs` | Resolved relative to `base_dir` passed to `setup_logging()`. |
| `filename` | string | `application.log` | Basename only; path traversal rejected. |
| `console.enabled` | bool | `false` | stderr stream handler. |
| `console.level` | string | `WARNING` | Console threshold. |
| `rotation.enabled` | bool | `false` | Enables time-based rotation handler. |
| `rotation.mode` | string | `DAILY` | `DAILY` or `INTERVAL_DAYS`. |
| `rotation.interval_days` | int | `7` | Required for `INTERVAL_DAYS`; integer ≥ 1. |
| `rotation.compress` | bool | `true` | Gzip archives when rotating. |
| `rotation.compression_level` | int | `6` | Gzip level 1–9. |
| `retention.enabled` | bool | `false` | Delete expired archives. |
| `retention.days` | int | `90` | Integer ≥ 1. |
| `retention.cleanup_on_startup` | bool | `true` | Run retention once during `setup_logging()`. |
| `security.redact_sensitive_data` | bool | `true` | Best-effort redaction (see limitations). |
| `security.redact_fields` | list | `[]` | Extra field names; defaults include `password`, `token`, etc. |

Example: [`examples/config.json`](examples/config.json)

---

## Rotation, archive layout, retention

```text
logs/
├── cancel_5534.log
├── archive/
│   ├── cancel_5534.2026-10-07_2026-10-13.log.gz
│   └── cancel_5534.2026-10-14_2026-10-20.log.gz
└── .logging_state/
    ├── cancel_5534.rotation.json
    └── cancel_5534.rotation.lock
```

- **DAILY**: rotate after the calendar day changes (Bangkok).
- **INTERVAL_DAYS**: rotate after `period_end`; state persists across cron restarts.
- **Locking**: `fcntl.flock` on `.rotation.lock` (Linux/CentOS 7).
- **Compression**: temp `*.gz.tmp` then atomic rename; failed gzip keeps the uncompressed archive.
- **Retention**: deletes only matching archived files under `archive/` by embedded date range; never deletes the active log file.

---

## Cronjob example

```bash
0 * * * * cd /path/to/app && PYTHONPATH=./lib python3 example_cron.py >>/dev/null 2>&1
```

Use a **separate log filename per concurrent instance** if multiple cron processes may overlap without coordination.

---

## Daemon example

Long-running processes should call `setup_logging()` once at startup and `shutdown_logging()` on graceful exit. Rotation is evaluated on each log emit (no `sleep` in logging threads).

---

## Running tests

```bash
cd TrueCorp-Python-Core
python3 -m unittest discover -s tests -v
```

**Note:** CI/dev environments may run a newer Python (e.g. 3.12). Syntax targets 3.6, but **runtime certification on Python 3.6 / CentOS 7 must be done in your target environment** before declaring `1.0.0` stable.

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| No log file | `logging.enabled`, directory permissions, `base_dir` when using relative paths. |
| Duplicate lines | Multiple `setup_logging()` with different configs on same process — check warnings. |
| Rotation not running | `rotation.enabled`, state under `.logging_state/`, lock permissions. |
| gzip failures | Disk space, `archive/` permissions; uncompressed archive should remain. |
| Missing run ID | Call `set_run_context(run_id=...)` in the same thread before logging. |

---

## Versioning

- Single source of truth: [`VERSION`](VERSION) (development/releases)
- Portable copy shipped inside [`truecorp_core/VERSION`](truecorp_core/VERSION) for FTP/SFTP deployments
- Module: `truecorp_core.__version__` / `truecorp_core/version.py`
- Release tags: `vX.Y.Z` (manual — not created by the library)
- History: [`CHANGELOG.md`](CHANGELOG.md)

---

## Related documents

- [`COMPATIBILITY.md`](COMPATIBILITY.md) — platform limits, multi-process policy, redaction limits
- [`CHANGELOG.md`](CHANGELOG.md)
