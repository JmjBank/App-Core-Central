#!/usr/bin/env python
"""READ-ONLY server preflight for truecorp_core. Writes nothing, deletes nothing.

    python3 tools/preflight.py --lib /path/to/APP/lib --log-dir /path/to/APP/logs

Exit code 0 = all checks passed (warnings allowed), 1 = at least one check failed.
"""
import argparse
import os
import platform
import sys

results = []


def report(status, message):
    results.append(status)
    print("[%s] %s" % (status, message))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lib", help="directory that CONTAINS the truecorp_core folder (e.g. APP/lib)")
    parser.add_argument("--log-dir", help="log directory to check (must already exist)")
    args = parser.parse_args(argv)

    info = sys.version_info
    report("PASS" if info[:2] >= (3, 6) else "FAIL", "python %s (%s)" % (platform.python_version(), sys.executable))
    if info[:2] != (3, 6):
        report("WARN", "target runtime is Python 3.6.x; this interpreter is %d.%d" % info[:2])
    for module in ("logging", "gzip", "json", "zlib", "threading", "fcntl"):
        try:
            __import__(module)
            report("PASS", "stdlib module '%s' available" % module)
        except ImportError:
            report("FAIL" if module != "fcntl" else "WARN", "stdlib module '%s' missing" % module)

    if args.lib:
        sys.path.insert(0, os.path.abspath(args.lib))
        try:
            import truecorp_core
            report("PASS", "truecorp_core %s importable from %s" % (truecorp_core.__version__, truecorp_core.__file__))
            from truecorp_core.logging import setup_logging  # noqa: F401  (import check only, nothing is set up)
            report("PASS", "truecorp_core.logging imports cleanly")
        except Exception as exc:  # noqa: preflight must report any import problem, not crash
            report("FAIL", "cannot import truecorp_core from %s: %s" % (args.lib, exc))

    if args.log_dir:
        path = os.path.abspath(args.log_dir)
        if not os.path.isdir(path):
            report("FAIL", "log directory %s does not exist (create it through your change procedure)" % path)
        else:
            ok = os.access(path, os.W_OK | os.X_OK)
            report("PASS" if ok else "FAIL", "log directory %s is %swritable by this user" % (path, "" if ok else "NOT "))
            try:
                stat = os.statvfs(path)
                free_mb = stat.f_bavail * stat.f_frsize // (1024 * 1024)
                report("PASS" if free_mb >= 100 else "WARN", "free disk space: %d MB" % free_mb)
            except (AttributeError, OSError) as exc:
                report("WARN", "cannot read free disk space: %s" % exc)
    print("preflight: %s" % ("FAILED" if "FAIL" in results else "OK"))
    return 1 if "FAIL" in results else 0


if __name__ == "__main__":
    sys.exit(main())
