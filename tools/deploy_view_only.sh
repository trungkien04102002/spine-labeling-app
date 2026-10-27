#!/usr/bin/env bash
# Put a view-only copy of the app on a cheap Vast.ai box: clinicians look at
# studies already graded elsewhere, so nothing here runs a model.
#
#   tools/deploy_view_only.sh <SSH_PORT> <SSH_HOST> <BACKUP_TGZ> [ENV_FILE]
#
# BACKUP_TGZ holds data/<study dirs> and spine.final.db, taken on the box that
# graded them (see memory: box4090-20261026/final_view.tgz). Paths in the DB
# are absolute under /workspace/spine-labeling-app, so the app goes to the
# same place here and nothing needs rewriting. ENV_FILE is that box's
# backend/.env; VIEW_ONLY is forced on whatever it says.
#
# Skipped on purpose, unlike deploy_box.sh: model weights, TotalSpineSeg and
# model B (~2 GB and ~15 minutes). torch still installs, because the backend
# imports it at startup, but as the small CPU build.
set -uo pipefail

PORT="${1:-}"; HOST="${2:-}"; TGZ="${3:-}"; ENVF="${4:-}"
if [ -z "$PORT" ] || [ -z "$HOST" ] || [ ! -f "$TGZ" ]; then
  echo "usage: $0 <SSH_PORT> <SSH_HOST> <BACKUP_TGZ> [ENV_FILE]" >&2; exit 1
fi
LOCAL="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE=/workspace/spine-labeling-app
SSH=(ssh -p "$PORT" -o BatchMode=yes -o ConnectTimeout=20 "root@$HOST")
T0=$(date +%s)
step() { echo ""; echo "── $* ──"; }

step "1 · code"
"${SSH[@]}" "mkdir -p $REMOTE" || exit 1
rsync -az -e "ssh -p $PORT -o BatchMode=yes" --delete \
  --exclude node_modules --exclude .venv --exclude backend/data \
  --exclude __pycache__ --exclude '*.pth' --exclude '*.db' --exclude .git \
  --exclude tss-venv --exclude 'frontend/dist' --exclude '.run' \
  --exclude 'backend/models/weights' --exclude 'backend/.env' --exclude '/data/' \
  "$LOCAL/" "root@$HOST:$REMOTE/" || exit 1

step "2 · data + database"
scp -q -P "$PORT" "$TGZ" "root@$HOST:/root/view_data.tgz" || exit 1
"${SSH[@]}" "cd $REMOTE/backend && mkdir -p data && tar xzf /root/view_data.tgz \
  && mv -f spine.final.db spine.db && ls -d data/* | wc -l" || exit 1

step "3 · backend env (CPU torch)"
"${SSH[@]}" "cd $REMOTE/backend && (command -v python3 >/dev/null || apt-get install -y python3) \
  && ([ -d .venv ] || python3 -m venv .venv) \
  && .venv/bin/pip install -q --upgrade pip \
  && .venv/bin/pip install -q torch torchvision --index-url https://download.pytorch.org/whl/cpu \
  && .venv/bin/pip install -q -r requirements.txt \
  && .venv/bin/python -c 'import torch, SimpleITK, fastapi; print(\"deps ok, torch\", torch.__version__)'" || exit 1

step "4 · .env"
if [ -n "$ENVF" ] && [ -f "$ENVF" ]; then
  scp -q -P "$PORT" "$ENVF" "root@$HOST:$REMOTE/backend/.env"
fi
"${SSH[@]}" "cd $REMOTE/backend && touch .env \
  && grep -q '^MYSQL_DSN=' .env || echo 'MYSQL_DSN=sqlite:///./spine.db' >> .env; \
  sed -i '/^VIEW_ONLY=/d;/^SEG_DEVICE=/d;/^TOTALSPINESEG_BIN=/d' .env && echo 'VIEW_ONLY=true' >> .env && cat .env | grep -v PASSWORD"

step "5 · frontend"
( cd "$LOCAL/frontend" && VITE_API_URL="" npx vite build --outDir "$LOCAL/.run/dist_view" --emptyOutDir >/dev/null ) || exit 1
rsync -az --delete -e "ssh -p $PORT -o BatchMode=yes" "$LOCAL/.run/dist_view/" "root@$HOST:$REMOTE/frontend/dist/" || exit 1

step "6 · public port + supervisor"
"${SSH[@]}" 'bash -s' <<'REMOTE_SH' || exit 1
set -e
PUB=$(tr '\0' '\n' < /proc/1/environ | grep '^VAST_TCP_PORT_72299=' | cut -d= -f2)
[ -n "$PUB" ] || { echo "no VAST_TCP_PORT_72299: open port 72299 in the template" >&2; exit 1; }
if [ -f /etc/portal.yaml ]; then
  cp -n /etc/portal.yaml /etc/portal.yaml.bak 2>/dev/null || true
  python3 - <<'PY'
import re
p = "/etc/portal.yaml"; s = open(p).read()
open(p, "w").write(re.sub(r"\n  Syncthing:\n(?:    .*\n)+", "\n", s))
PY
fi
# By pid: "pkill -f syncthing serve" would match this very shell's command line.
for pid in $(pgrep -f "syncthing serve" || true); do [ "$pid" != "$$" ] && kill "$pid" 2>/dev/null || true; done
cat > /etc/supervisor/conf.d/spine_backend.conf <<CONF
[program:spine_backend]
command=/workspace/spine-labeling-app/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $PUB
directory=/workspace/spine-labeling-app/backend
environment=TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD="1",FRONTEND_DIST="/workspace/spine-labeling-app/frontend/dist"
autostart=true
autorestart=true
stdout_logfile=/var/log/spine_backend.log
redirect_stderr=true
stopasgroup=true
killasgroup=true
CONF
supervisorctl reread >/dev/null; supervisorctl update >/dev/null; supervisorctl restart spine_backend >/dev/null || true
for i in $(seq 1 30); do curl -sf "localhost:$PUB/health" >/dev/null && break; sleep 2; done
echo "public port $PUB"
echo "health     $(curl -s localhost:$PUB/health)"
echo "app_config $(curl -s localhost:$PUB/app_config)"
echo "rooms      $(curl -s localhost:$PUB/readers/public)"
REMOTE_SH

echo ""; echo "══ done in $(( $(date +%s) - T0 ))s ══"
