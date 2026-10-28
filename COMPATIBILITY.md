# Compatibility & Limitations

## Python

| Topic | Detail |
|-------|--------|
| Target runtime | **CPython 3.6.x** |
| Standard library only | No third-party packages required |
| Dev/CI testing | May use newer Python; **does not replace** validation on 3.6 production hosts |

Features intentionally avoided (post-3.6): `zoneinfo`, `dataclasses`, walrus operator, `logging.Handler.set_name`, etc.

Timezone for timestamps uses a **fixed UTC+7** offset (correct for Asia/Bangkok, which has no DST).

## Operating system

| Topic | Detail |
|-------|--------|
| Primary target | RHEL/CentOS 7 |
| File locking | `fcntl.flock` for rotation/retention coordination |
| Deployment | Copy-tree / FTP / SFTP — no root, no system Python changes |

Not supported: Windows-specific APIs, Docker-only workflows, external log collectors in Phase 1.

## External dependencies

**None.** No Redis, Elasticsearch, Oracle, or centralized log server required for Phase 1.

## Multi-process / concurrent cron

| Policy | Detail |
|--------|--------|
| Default | Multiple processes must **not** share one active log file without coordination |
| Rotation | Serialized with `flock` on the rotation lock file |
| Recommendation | Separate `filename` (or separate log directories) per parallel worker |
| Threading | `set_run_context()` is **thread-local**; not shared across processes |

`threading.Lock` does **not** protect across processes.

Stale lock recovery relies on process exit releasing `flock` — normal on Linux when the owner terminates.

## Security redaction

Redaction is **best-effort**:

- Known key names and simple `key=value` / `Bearer` patterns are masked.
- Cannot guarantee detection of all secrets in free-form text.
- Do not log raw authentication headers, private keys, or database passwords intentionally.

See unit tests in `tests/test_security.py` for covered cases.

## Logging reliability

| Scenario | Behavior |
|----------|----------|
| Gzip failure | Uncompressed archive retained; error written to stderr |
| Disk full | Compression/rotation may fail; active log append may fail (stdlib behavior) |
| Corrupt rotation state | State file re-initialized; may adjust next rotation window |
| Permission denied on cleanup | Retention counts failures; does not disable active logging |

## Path safety

- Relative log paths resolve from `base_dir` supplied to `setup_logging()`.
- Path traversal in `filename` is rejected.
- Retention skips symlinks and only deletes files matching the application log prefix in `archive/`.

## Known gaps before `1.0.0`

- No automated bump of `VERSION` (release process is manual).
- Python **3.6** execution not verified in this repository’s default CI image (3.12 used for unit tests).
- No built-in log shipping / centralized search.
- Redaction is not a compliance control on its own.

## Upgrade notes (`0.1.0` → future)

1. Deploy new `truecorp_core/` to staging.
2. Run preflight import + config validation.
3. Swap directory during change window; keep backup for rollback.
4. Confirm `truecorp_core.__version__` and sample log line format in UAT.

Breaking changes will increment **MAJOR** version per SemVer and be listed in `CHANGELOG.md`.
