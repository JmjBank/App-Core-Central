# TrueCorp-Python-Core

**Version:** 0.1.0 (development; target stable release `1.0.0`)

Shared Python library for several applications. Phase 1 contains only the **Core Logging Library**:
plain-text logs, calendar rotation, gzip archives, retention, run/tracking context and sensitive-data redaction.

- Python **3.6+**, **standard library only**, RHEL/CentOS 7, no root, no `pip install`.
- Does not touch the application's existing logging (handlers live on a separate `truecorp` logger).
- Details of what was and was not verified: [COMPATIBILITY.md](COMPATIBILITY.md). Deployment/rollback: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Installation (portable, FTP/SFTP)

Copy the `truecorp_core/` directory into your application, e.g. `APP_CANCEL_5534/lib/truecorp_core/`, and point
`PYTHONPATH` at `lib`:

```sh
export PYTHONPATH="/path/to/APP_CANCEL_5534/lib${PYTHONPATH:+:$PYTHONPATH}"
python3 main.py
```

See `examples/run.sh`. Upload without overwriting a library that is in use: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Quick start

```python
import json
from truecorp_core.logging import setup_logging, get_logger, set_run_context, clear_run_context, shutdown_logging

config = json.load(open("config.json"))            # your own config; only the "logging" section is used
setup_logging(config["logging"])                   # relative paths resolve from the script's directory

logger = get_logger("APP_CANCEL_5534")
set_run_context("RUN-20261028-001", tracking_id="ABC123")

logger.info("Application started")
logger.info("processed=%s", 42)                    # lazy %-formatting works as usual
logger.info("fetched", extra={"event": "IOM_GET_SUCCESS", "duration_ms": 1250})
try:
    raise RuntimeError("boom")
except RuntimeError:
    logger.exception("Unexpected error")          # traceback + error_type=RuntimeError

clear_run_context()
shutdown_logging()
```

Output (Asia/Bangkok time, one event per line):

```text
2026-10-28 15:00:01 [INFO] [APP_CANCEL_5534] [RUN-20261028-001] Application started tracking_id=ABC123
2026-10-28 15:00:03 [INFO] [APP_CANCEL_5534] [RUN-20261028-001] fetched tracking_id=ABC123 event=IOM_GET_SUCCESS duration_ms=1250
2026-10-28 15:00:04 [ERROR] [APP_CANCEL_5534] [RUN-20261028-001] Unexpected error tracking_id=ABC123 error_type=RuntimeError
    Traceback (most recent call last):
    ...
```

Format rules: `timestamp [LEVEL] [name] [run_id] message key=value ...`. Missing run id prints `-`; missing optional
fields are omitted. Known fields come first in a fixed order (`tracking_id async_id batch_id event step duration_ms
hostname pid`), then any other `extra` fields alphabetically. Values containing spaces/quotes are quoted; newlines and
control characters are escaped (`\n`, `\x1b`), and every traceback line is indented, so a log line cannot be forged.
Grep examples: `grep 'tracking_id=ABC123' app.log`, `grep 'event=IOM_GET_FAILED' app.log`, `grep '\[RUN-20261028-001\]'`.

## Logging API

| Function | Purpose |
|---|---|
| `setup_logging(config=None, base_dir=None)` | Validate config and install handlers. **Idempotent**: same config again = no-op. Different config = new handlers replace the old ones (last call wins). Invalid config -> `ConfigError`, nothing changes. Unusable log directory -> `LoggingSetupError` (fail fast). |
| `get_logger(name)` | Standard `logging.Logger` named `truecorp.<name>`: `debug/info/warning/error/critical/exception`, `extra=`, lazy args. |
| `set_run_context(run_id, **fields)` | Set run id and business fields (e.g. `tracking_id`, `batch_id`) for the **current thread**. Replaces the previous context entirely, so nothing leaks between jobs. |
| `clear_run_context()` | Empty the current thread's context. |
| `run_context(run_id, **fields)` | `with` block: scoped context, previous context restored afterwards. |
| `shutdown_logging()` | Flush and close handlers. Safe to call repeatedly. |
| `cleanup_logs()` | Run retention cleanup now; returns counts or `None` (not set up / another process is busy). |

**Thread/process behaviour:** context is thread-local and not inherited by new threads (call `set_run_context` in each
worker); processes never share context. Handlers are thread-safe; cross-process safety is described below.

**What `setup_logging` never does:** it does not modify your config dict, does not touch the root logger, and never
raises at runtime (rotation/gzip/retention/disk-full problems are reported on stderr and as `WARNING` lines in the log;
the application keeps running).

## Configuration reference (`logging` section)

Every key is optional. Unknown keys are rejected (a typo must not silently change retention).

| Key | Type | Default | Validation |
|---|---|---|---|
| `enabled` | bool | `true` | `false` = nothing is written, no files created |
| `level` | str | `"INFO"` | `DEBUG INFO WARNING ERROR CRITICAL` (any case) |
| `directory` | str | `"./logs"` | relative = from `base_dir` (default: directory of the running script, **not** the CWD); `..` escaping the base is rejected; absolute allowed; system dirs (`/etc /usr /bin /sbin /boot /dev /proc /sys /lib /lib64 /`) rejected |
| `filename` | str | `"app.log"` | plain file name: no `/`, `\`, `..`; not `archive` / `.logging_state` |
| `allowed_roots` | list[str] | none | if set, the resolved directory must be inside one of them |
| `console.enabled` | bool | `false` | writes to **stderr** |
| `console.level` | str | `"WARNING"` | as `level` |
| `rotation.enabled` | bool | `true` | |
| `rotation.mode` | str | `"DAILY"` | `DAILY` or `INTERVAL_DAYS` |
| `rotation.interval_days` | int | `7` | integer >= 1 (bool/str/float rejected); used by `INTERVAL_DAYS` only |
| `rotation.anchor_date` | str | first run date | `YYYY-MM-DD`; fixes the calendar so servers can share the same cycle |
| `rotation.compress` | bool | `true` | gzip archives |
| `rotation.compression_level` | int | `6` | 1-9 |
| `retention.enabled` | bool | `true` | |
| `retention.days` | int | `90` | integer >= 1 |
| `retention.cleanup_on_startup` | bool | `true` | |
| `security.redact_sensitive_data` | bool | `true` | |
| `security.redact_fields` | list[str] | built-in list | **added to** the built-ins `password passwd token authorization api_key secret credentials private_key`; matched as substrings of field names (`access_token`, `db_password`...) |

## Rotation, gzip, retention

Files (names as in the project specification):

```text
logs/
├── cancel_5534.log                                  <- active log (never compressed)
├── archive/
│   ├── cancel_5534.2026-10-07_2026-10-13.log.gz
│   └── cancel_5534.2026-10-14_2026-10-20.log.gz
└── .logging_state/
    ├── cancel_5534.rotation.json                    <- anchor + current period start (checksummed, atomic)
    └── cancel_5534.lock
```

- **Calendar:** period boundaries are `anchor + k x interval` days in Asia/Bangkok. `DAILY` = interval 1.
  The anchor is `rotation.anchor_date` or the date of the first run (stored in the state file), so a cron restart never
  resets the cycle. If the job was down for weeks, the next start archives once (named after the period that ended)
  and continues in the period that contains today; empty periods are skipped.
- **Rotation steps:** rename active -> `archive/<name>.<start>_<end>.log` (atomic) -> save state -> reopen active -> gzip.
  Name collision: `...log.gz` exists -> `....1.log.gz`, `....2.log.gz`; an existing archive is never overwritten.
- **Gzip:** `.log.gz.tmp` -> read back and compare size + CRC32 -> atomic rename -> only then delete the original.
  Any failure (permission denied, disk full, corrupt output) keeps the original `.log` and the next start/rotation retries.
  A kill at any point is repaired at the next start; a bad `.gz` is renamed `*.corrupt-<time>`, never deleted.
- **Retention:** deletes only `<name>.<start>_<end>[.n].log[.gz]` in `archive/` whose **end date** is more than `days`
  days ago. Never the active log, other applications' files, symlinks, or an archive whose original/temp file still exists.
  Runs at startup, after each rotation, and on `cleanup_logs()`. Result line example:
  `retention cleanup scanned=14 expired=3 deleted=3 failed=0 skipped=0` (written at INFO when something was
  expired/failed, at DEBUG otherwise, so a cron job that starts every minute does not spam the log).
- **State file damaged/missing:** missing = new cycle starts today and the existing log is kept; damaged = moved to
  `*.corrupt-<time>` and rebuilt.

Configuration examples:

```json
{"rotation": {"mode": "DAILY"},                        "retention": {"days": 30}}
{"rotation": {"mode": "INTERVAL_DAYS", "interval_days": 7, "anchor_date": "2026-10-07"}}
{"rotation": {"enabled": false}, "retention": {"enabled": false}}
```

## Cronjob example

`examples/example_cron.py` (run `python3 examples/example_cron.py`): a new process per run; the same active log and
the same rotation cycle are used by every run.

```cron
*/5 * * * * cd /path/to/APP_CANCEL_5534 && ./run.sh >> /dev/null 2>&1
```

## Daemon example

`examples/example_app.py --iterations 0`: one long-running process; rotation and retention happen inside it when the
Bangkok date crosses a boundary, with no `sleep` in the logging path. Worker threads call `set_run_context` themselves.

## Concurrency

Several cron processes may start at the same time. They append to the same file; one of them wins a non-blocking
`flock` and rotates, the others skip rotation and re-open the new file on their next write. See
[COMPATIBILITY.md](COMPATIBILITY.md) for the exact policy and its limits.

## Security

Redaction covers `key=value`, `key: value`, JSON `"key": "value"`, `Authorization`/`Bearer`/`Basic` values, JWT-shaped
tokens, PEM private-key blocks, `scheme://user:password@host` URLs and structured `extra` fields whose **name** matches
the redact list. Redaction is applied to messages, arguments, extra fields and tracebacks.

**Limitations (it is not a guarantee):** an unquoted secret containing spaces (`password=my secret`) is cut at the
first space; a secret without a recognisable field name, Oracle `user/password@tns` strings and secrets split across
several log calls are not detected; field-name matching is by substring, so harmless fields such as `token_count`
are redacted too. Never log credentials, raw `Authorization` headers, private keys or database passwords on purpose.

## Troubleshooting

| Symptom | Check |
|---|---|
| `ConfigError: unknown key(s)` | Typo, or you passed the whole config; pass `config["logging"]`. |
| `LoggingSetupError: cannot prepare log directory` | Directory/permission/disk; run `tools/preflight.py --log-dir ...`. |
| Logs appear in an unexpected folder | Relative paths resolve from the script directory (`base_dir`), not the CWD. |
| `[truecorp_core.logging] ... failed, will retry` on stderr | Rotation/gzip/retention problem (permission, disk). The log itself keeps working; fix and the next start retries. |
| Archive stays `.log` (not `.gz`) | Compression failed; see the WARNING line; it is retried at next start/rotation. |
| `*.corrupt-<time>` files | Evidence of a damaged state or archive; safe to delete manually after review. |
| `import logging` picks the wrong module | Never run a script from inside `truecorp_core/logging/`. |

## Development

```sh
python3 -m unittest discover -s tests -t .        # all tests (no Oracle / Elasticsearch / network)
python3 tools/check_version.py                    # version consistency
```

Tests use only `unittest`. Layout: `truecorp_core/logging/` = `config`, `factory` (public API), `formatter`,
`context`, `security`, `rotation` (handler + state), `compression`, `retention`, `lock`. Future Database/SSH/
Elasticsearch/HTTP/Alert modules will be sibling packages under `truecorp_core/`; nothing of them exists yet.

## Versioning & release

Semantic Versioning `MAJOR.MINOR.PATCH`; development starts at `0.1.0`, first stable release is `1.0.0`.
`truecorp_core/VERSION` is the single version source read by `truecorp_core.__version__`; the root `VERSION` must equal
it and `tools/check_version.py` (also run by the tests) checks both, the newest `CHANGELOG.md` heading and the
`Version:` lines of README/COMPATIBILITY. A version changes only in a release change, never at runtime. Release steps
(by a person): update both `VERSION` files + CHANGELOG + docs, run the check and tests, merge, then tag `vX.X.X`.
