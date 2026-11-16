#!/usr/bin/env bash
# One command: check Python, create the database and .env, install the `orphan-radar` launcher,
# run the tests, then run a full scan with every source that needs no credentials.
#   ./setup.sh            # install + full scan (about 10-15 minutes, mostly polite rate-limit waits)
#   ./setup.sh --no-scan  # install only
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
"$PY" - <<'PYCHECK'
import sys
if sys.version_info < (3, 11):
    sys.exit(f"Orphan Radar needs Python 3.11 or newer (found {sys.version.split()[0]}).")
PYCHECK

# Optional: the Claude provider uses the official SDK. Installed only if you configured it.
if grep -qE '^ORPHAN_RADAR_LLM_PROVIDER=anthropic' .env 2>/dev/null || [ "${ORPHAN_RADAR_LLM_PROVIDER:-}" = "anthropic" ]; then
  "$PY" -c "import anthropic" 2>/dev/null || "$PY" -m pip install --user "anthropic>=0.40" || echo "warning: could not install the anthropic SDK; language-model steps will be skipped"
fi

"$PY" -m orphan_radar init

mkdir -p bin
cat > bin/orphan-radar <<LAUNCH
#!/usr/bin/env bash
cd "$(pwd)" && exec "$PY" -m orphan_radar "\$@"
LAUNCH
chmod +x bin/orphan-radar
echo "launcher: $(pwd)/bin/orphan-radar  (add $(pwd)/bin to your PATH, or use ./bin/orphan-radar)"

"$PY" -m unittest discover -s tests -t . -q

if [ "${1:-}" != "--no-scan" ]; then
  "$PY" -m orphan_radar sources
  "$PY" -m orphan_radar scan
  "$PY" -m orphan_radar export
  echo
  echo "Dashboard: ./bin/orphan-radar serve   then open http://127.0.0.1:8765/"
fi
