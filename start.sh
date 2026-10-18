#!/usr/bin/env bash
# Start OpenCrup.
#
# Usage: ./start.sh [-p PORT] [-H HOST] [-d DB]
set -euo pipefail

PORT=4321
HOST=127.0.0.1
DB=""

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Options:
  -p PORT   HTTP port (default: 4321)
  -H HOST   Bind address (default: 127.0.0.1)
  -d PATH   opencode database (default: ~/.local/share/opencode/opencode.db)
  -h        Show this help
EOF
}

while getopts ":p:H:d:h" opt; do
  case "$opt" in
    p) PORT=$OPTARG ;;
    H) HOST=$OPTARG ;;
    d) DB=$OPTARG ;;
    h) usage; exit 0 ;;
    :) echo "option -$OPTARG requires an argument" >&2; exit 1 ;;
    \?) echo "unknown option: -$OPTARG" >&2; usage >&2; exit 1 ;;
  esac
done

case "$PORT" in
  '' | *[!0-9]*) echo "error: port must be a number (got '$PORT')" >&2; exit 1 ;;
esac

# Fail fast with a clear message if the port is already taken.
if command -v lsof >/dev/null 2>&1 && lsof -ti ":$PORT" >/dev/null 2>&1; then
  PID=$(lsof -ti ":$PORT" | head -1)
  echo "error: port $PORT is already in use (pid $PID)" >&2
  echo "stop it with: kill $PID   —   or use another: ./start.sh -p <port>" >&2
  exit 1
fi

cd "$(dirname "$0")"

export PORT HOST
[ -n "$DB" ] && export OPENCODE_DB="$DB"

echo "OpenCrup → http://localhost:$PORT"
exec python scripts/server.py
