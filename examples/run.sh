#!/bin/sh
# Example wrapper for the portable layout  APP/{main.py,config.json,lib/truecorp_core,logs,run.sh}
# No pip, no sudo: the library is found through PYTHONPATH only.
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHONPATH="$APP_DIR/lib${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH
cd "$APP_DIR" || exit 1
exec python3 "$APP_DIR/main.py" "$@"
