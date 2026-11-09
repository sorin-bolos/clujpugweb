#!/usr/bin/env bash
# Runs tools/puz/puz.py with a Python that has the pipeline's packages: `py -3.13` on
# the Windows laptop (Git Bash), python3 elsewhere, e.g. in a Claude Code cloud
# session. PUZ_PYTHON overrides both.
here="$(cd "$(dirname "$0")" && pwd)"
if [ -n "$PUZ_PYTHON" ]; then
  exec $PUZ_PYTHON "$here/puz.py" "$@"
elif command -v py >/dev/null 2>&1; then
  exec py -3.13 "$here/puz.py" "$@"
else
  exec python3 "$here/puz.py" "$@"
fi
