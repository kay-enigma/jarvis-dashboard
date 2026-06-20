#!/bin/bash
# Double-click this on macOS to launch Jarvis.
# It starts the local server and opens the dashboard in your browser.
# Close the Terminal window (or Ctrl-C) to shut Jarvis down.

cd "$(dirname "$0")" || exit 1

# Prefer the project venv if it exists, else fall back to system python.
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi

PORT="${JARVIS_PORT:-8000}"
URL="http://127.0.0.1:${PORT}"

echo "── JARVIS ───────────────────────────────"
echo "  starting reactor on ${URL}"
echo "  state file: $($PY -m jarvis.cli where 2>/dev/null | head -1)"
echo "  (close this window to shut down)"
echo "─────────────────────────────────────────"

# Open the browser once the server is up.
( sleep 2; open "$URL" ) &

exec "$PY" -m jarvis.cli serve --port "$PORT"
