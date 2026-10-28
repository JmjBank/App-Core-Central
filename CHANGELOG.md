# Changelog

All notable changes to **TrueCorp-Python-Core** are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-28

### Added

- Initial **Core Logging Library** under `truecorp_core.logging`.
- Public API: `setup_logging`, `get_logger`, `set_run_context`, `clear_run_context`, `shutdown_logging`.
- Plain-text formatter with **Asia/Bangkok (UTC+7)** timestamps, application name, run ID, and grep-friendly key-value fields.
- JSON-driven configuration validation with safe defaults and path checks.
- Time-based rotation modes **DAILY** and **INTERVAL_DAYS** with persistent state (`.logging_state/*.rotation.json`).
- Cross-process rotation locking via `fcntl.flock` on Linux.
- Gzip compression for archived logs with temp-file + integrity verification workflow.
- Retention cleanup for expired archives with active-log protection and prefix scoping.
- Sensitive field redaction and control-character sanitization (best-effort, not exhaustive).
- Portable deployment (copy `truecorp_core/` — no `pip install` required).
- Examples under `examples/` and `unittest` coverage under `tests/`.
- Documentation: `README.md`, `COMPATIBILITY.md`.

### Notes

- Development release targeting stable **1.0.0** after production acceptance testing on **Python 3.6 / CentOS 7**.

[0.1.0]: https://example.local/truecorp-python-core/releases/tag/v0.1.0
