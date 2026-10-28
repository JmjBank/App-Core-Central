# Changelog

All notable changes are listed per version. Format: [Keep a Changelog](https://keepachangelog.com/),
versioning: [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`).
Versions change only through the release process (see README, "Versioning & release"); git tags use `vX.X.X`
and are created by a person, never automatically.

## [0.1.0] - 2026-10-28

First development version of **TrueCorp-Python-Core** (Core Logging Library). Target for the first stable
release is `1.0.0`, after the Acceptance Criteria are verified on a real CentOS 7 server.

### Added
- `truecorp_core.logging`: `setup_logging`, `get_logger`, `set_run_context`, `clear_run_context`,
  `shutdown_logging`, plus `cleanup_logs` (manual retention) and `run_context` (scoped context).
- Plain-text log format, Asia/Bangkok timestamps, run id, optional `key=value` fields, exception traceback,
  `error_type`, newline/control-character escaping (log-forgery protection).
- Validated configuration with defaults, unknown-key rejection, path-traversal and protected-directory checks,
  base-directory based relative paths.
- Time-based rotation: `DAILY` and `INTERVAL_DAYS` with a checksummed, atomically written state file and an
  explicit calendar anchor; cron-restart safe, daemon safe, month/year boundary safe, collision-free archive names.
- Gzip of archived logs with temp file, integrity verification, no overwrite, and crash recovery.
- Retention cleanup (age taken from the archive file name), startup and manual, with found/deleted/failed counts.
- Sensitive-data redaction (field names and text patterns) with documented limitations.
- Cross-process safety: non-blocking `flock` for rotation/retention, inode check before writes.
- Examples (`examples/`), read-only server preflight (`tools/preflight.py`), release version check
  (`tools/check_version.py`), deployment and rollback guide (`docs/DEPLOYMENT.md`).
- `unittest` suite (unit, integration, multi-process).

### Changed
- Root `VERSION` set from the placeholder `1.0.0` to `0.1.0` as required by the project plan.
- `README.MD` (empty) renamed to `README.md` to avoid a case-collision on case-insensitive checkouts.

### Fixed
- Nothing yet (first version).

### Breaking Changes
- None. (The repository previously contained only an empty README and `VERSION` = `1.0.0`.)
