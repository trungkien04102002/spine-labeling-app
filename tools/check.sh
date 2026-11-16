#!/usr/bin/env bash
# One command that says whether this checkout works.
#
#   tools/check.sh          backend tests + frontend lint/build   (no GPU, ~2 min)
#   tools/check.sh --gpu    ...then a real upload + grading through the API
#                           (needs weights + TotalSpineSeg; starts the backend
#                           if nothing is listening on :8000)
#
# Exits non-zero at the first failure. Run from anywhere.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/backend/.venv/bin/python"
[ -x "$PY" ] || { echo "backend/.venv missing -- see README Quick start"; exit 1; }

echo "== 1/3 backend tests"
(cd "$REPO/backend" && "$PY" -m pytest -q -k "not end_to_end")

echo "== 2/3 frontend lint + build"
# Build into a temporary folder: on a server, frontend/dist is what users are
# served, and a plain build would bake in the default API URL.
OUT="$(mktemp -d)"
(cd "$REPO/frontend" && npm run --silent lint -- --quiet && npx tsc -b \
  && npx vite build --outDir "$OUT" --emptyOutDir >/dev/null)
rm -rf "$OUT"
echo "frontend OK"

if [ "${1:-}" != "--gpu" ]; then
  echo "== 3/3 skipped (pass --gpu to upload and grade a real volume)"
  echo "ALL CHECKS PASSED"
  exit 0
fi

echo "== 3/3 upload + grade a SPIDER volume"
STARTED=""
if ! curl -sf -o /dev/null http://127.0.0.1:8000/health; then
  "$REPO/run.sh" backend
  STARTED=1
  for _ in $(seq 1 60); do
    curl -sf -o /dev/null http://127.0.0.1:8000/health && break
    sleep 1
  done
fi
status=0
"$PY" "$REPO/tools/smoke_grade.py" || status=$?
[ -n "$STARTED" ] && "$REPO/run.sh" stop backend >/dev/null
[ "$status" -eq 0 ] && echo "ALL CHECKS PASSED"
exit "$status"
