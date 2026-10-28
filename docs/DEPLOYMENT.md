# Deployment & Rollback Guide (FTP/SFTP, no root)

**Version:** 0.1.0

Deployment to UAT/Production must follow your approved change procedure and permissions. Nothing in this repository
deploys automatically. Steps below only describe *how*, using a normal (non-root) user.

## Target layout

```text
APP_CANCEL_5534/
├── main.py
├── config.json
├── run.sh                      # sets PYTHONPATH (see examples/run.sh)
├── lib/
│   └── truecorp_core/          # the library (copied as a plain directory)
└── logs/                       # created by the library on first start (or by you)
```

Import in the application: `from truecorp_core.logging import setup_logging, get_logger`.
`PYTHONPATH` (Linux): `export PYTHONPATH="/path/to/APP_CANCEL_5534/lib${PYTHONPATH:+:$PYTHONPATH}"`.
No `pip`, `sudo`, system-Python change, package or Docker is needed.

## 1. Read-only preflight on the server (before uploading)

Upload only `tools/preflight.py` (or run it from a copy of the repository) and run:

```sh
python3 preflight.py --log-dir /path/to/APP_CANCEL_5534/logs        # before the library exists
python3 preflight.py --lib /path/to/APP_CANCEL_5534/lib --log-dir /path/to/APP_CANCEL_5534/logs   # after upload
```

It writes and deletes nothing. It checks the Python version (warns if it is not 3.6.x), the required standard-library
modules, that `truecorp_core` imports (and prints its version), that the log directory exists, is writable and has free
space. Exit code 1 = do not continue.

## 2. Upload without overwriting a library that is in use

Never upload on top of `lib/truecorp_core` while jobs or daemons use it (a process can import half-old/half-new files).
Use a **versioned directory and an atomic switch**:

```sh
# on the server, in APP_CANCEL_5534/
#   lib/                      <- PYTHONPATH points here
#   releases/truecorp_core-0.1.0/truecorp_core/   <- uploaded by FTP/SFTP
```

1. Upload to `releases/truecorp_core-0.1.0/truecorp_core/` (new path; nothing running uses it yet).
2. Check the upload is complete: compare file sizes/checksums (`cksum`) with your local copy, then
   `PYTHONPATH=releases/truecorp_core-0.1.0 python3 -c "import truecorp_core; print(truecorp_core.__version__)"`
   must print `0.1.0`.
3. Switch with one atomic rename of a symlink:
   `ln -sfn releases/truecorp_core-0.1.0 lib_new && mv -Tf lib_new lib`
   (`lib` is then a symlink to the release directory; running processes keep the files they already imported; new
   starts use the new version).
   If symlinks are not allowed, stop the application, rename `lib/truecorp_core` -> `lib/truecorp_core.prev`, rename the
   uploaded directory into place, start the application.
4. Restart long-running daemons during the agreed window; cron jobs pick the new version on their next start.
5. Run the application once and check `logs/<file>.log` contains the new lines and `.logging_state/` exists.

If you must keep the plain layout (`lib/truecorp_core` directly): upload to `lib/truecorp_core.new`, then, with the
application stopped, `mv lib/truecorp_core lib/truecorp_core.prev && mv lib/truecorp_core.new lib/truecorp_core`.

## 3. Configuration

Add (or merge) only a `logging` section into the application's config, see `examples/config.json`. Existing keys are not
modified. Relative `directory` values resolve from the script's directory, so cron's working directory does not matter.
Keep the `logs/` directory on a local disk (see COMPATIBILITY.md, limitation 1).

## 4. Rollback

The library only creates files below its own `logs/` directory (`archive/`, `.logging_state/`), so rollback never
needs data migration.

1. Stop the daemon / disable the cron entry (per your change procedure).
2. Switch back: `ln -sfn releases/truecorp_core-<previous> lib_new && mv -Tf lib_new lib`
   (or `mv lib/truecorp_core lib/truecorp_core.failed && mv lib/truecorp_core.prev lib/truecorp_core`).
3. If the application code was changed to call the library, restore the previous `main.py`/`config.json` from your backup.
4. Start the application, confirm it logs as before.
5. **Do not delete** `logs/`, `logs/archive/` or `.logging_state/`. Archives are normal gzip files readable with
   `zcat`/`gzip -dc`. A later re-deployment of the library continues the same rotation cycle from `.logging_state/`.
6. Keep `*.corrupt-*` files and the failed release directory until the cause is understood.

The state file is plain JSON (`anchor`, `period_start`, checksum). If a state file is ever unreadable, the library moves it
to `*.corrupt-<time>` and starts a new cycle; the existing log is kept.

## 5. Post-deployment checks (read-only)

```sh
tail -n 20 logs/cancel_5534.log
ls -l logs/archive/ logs/.logging_state/
zcat logs/archive/*.log.gz | tail -n 3            # after the first rotation
grep -c 'log maintenance failed' logs/cancel_5534.log
```
