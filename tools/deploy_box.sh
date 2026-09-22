#!/usr/bin/env bash
# Put this app on a fresh Vast.ai GPU box, from the laptop, in one command.
#
#   tools/deploy_box.sh <SSH_PORT> <SSH_HOST> [--with-replay]
#   tools/deploy_box.sh 54339 115.75.223.236
#
# Why a script and not a checklist: DEPLOY_VAST.md was followed by hand on
# 2026-09-21 and four of its steps were wrong (a stale clone, two wrong paths,
# and a summary that said "everything installed" on a box that could not grade).
# Prose drifts from the code; this runs the code.
#
# It is re-runnable: every step is idempotent, so re-running after a failure
# picks up where it left off rather than starting over.
#
# --with-replay also copies rsna_preprocessed (~8.2 GB, ~5 min) so the box can
# actually re-train. Without it /admin shows the run blocked, which is honest
# and fine unless you mean to train there.
set -uo pipefail

PORT="${1:-}"; HOST="${2:-}"; WITH_REPLAY="${3:-}"
if [ -z "$PORT" ] || [ -z "$HOST" ]; then
  echo "usage: $0 <SSH_PORT> <SSH_HOST> [--with-replay]" >&2; exit 1
fi

LOCAL="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE=/workspace/spine-labeling-app
RESEARCH="${RESEARCH_REPO:-$HOME/spinet-v2}"
SSH=(ssh -p "$PORT" -o BatchMode=yes -o ConnectTimeout=20 "root@$HOST")
CKPT_MD5=50101203903b1aa3bcf3d6103daa650e
T0=$(date +%s)
step() { echo ""; echo "── $* ────────────────────────────────"; }
secs() { echo "   ($(( $(date +%s) - $1 ))s)"; }

step "0 · reachable?"
"${SSH[@]}" 'echo ok' >/dev/null || { echo "cannot ssh" >&2; exit 1; }
"${SSH[@]}" 'nvidia-smi --query-gpu=name --format=csv,noheader; test -x /venv/main/bin/python && echo "/venv/main present"'

# The repo is often ahead of what is pushed, so ship the working tree rather
# than cloning. A clone on 2026-09-21 came back a month stale.
step "1 · code (rsync, not clone — main is usually ahead of origin)"
t=$(date +%s)
"${SSH[@]}" "mkdir -p $REMOTE"
rsync -az -e "ssh -p $PORT -o BatchMode=yes" --delete \
  --exclude node_modules --exclude .venv --exclude backend/data \
  --exclude __pycache__ --exclude '*.pth' --exclude '*.db' --exclude .git \
  --exclude tss-venv --exclude 'frontend/dist' --exclude '.run' \
  "$LOCAL/" "root@$HOST:$REMOTE/" || exit 1
secs $t

# None of these travel with the code: .gitignore excludes every weight file and
# all of backend/data. Copying beats downloading -- robots.ox.ac.uk is slow and
# has failed mid-transfer, and totalspineseg_init's fetch failed five times in
# a row on 2026-09-20 while the same bytes copied from here in twelve seconds.
step "2 · weights + frozen held-out set (~1.4 GB)"
t=$(date +%s)
"${SSH[@]}" "mkdir -p $REMOTE/backend/models/weights"
scp -P "$PORT" -o BatchMode=yes \
  "$LOCAL/backend/models/weights/phase2_cbam.pth" \
  "$LOCAL/backend/models/weights/ACTIVE" \
  "root@$HOST:$REMOTE/backend/models/weights/" >/dev/null || exit 1
( cd "$LOCAL/backend/spinenet" && tar czf - weights ) \
  | "${SSH[@]}" "tar xzf - -C $REMOTE/backend/spinenet" || exit 1
( cd "$LOCAL/backend" && tar czf - data/holdout_frozen ) \
  | "${SSH[@]}" "cd $REMOTE/backend && tar xzf -" || exit 1
secs $t

step "3 · vast_setup.sh (the long one, ~11 min)"
t=$(date +%s)
"${SSH[@]}" "cd $REMOTE && ./vast_setup.sh --skip-download 2>&1 | tail -25"
secs $t

# The interpreter depends on which install path ran. vast_setup.sh builds
# backend/.venv; a hand install uses /venv/main. Naming the wrong one gives
# "FATAL can't find command" and supervisor writes no log at all.
step "4 · backend under supervisor"
UVICORN=$("${SSH[@]}" "test -x $REMOTE/backend/.venv/bin/uvicorn && echo $REMOTE/backend/.venv/bin/uvicorn || echo /venv/main/bin/uvicorn")
echo "   uvicorn: $UVICORN"
"${SSH[@]}" "cat > /etc/supervisor/conf.d/spine_backend.conf <<EOF
[program:spine_backend]
command=$UVICORN app.main:app --host 127.0.0.1 --port 8000
directory=$REMOTE/backend
environment=TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=\"1\"
autostart=true
autorestart=true
stdout_logfile=/var/log/spine_backend.log
redirect_stderr=true
stopasgroup=true
killasgroup=true
EOF
supervisorctl reread >/dev/null; supervisorctl update >/dev/null; sleep 10
supervisorctl status spine_backend"

step "5 · studies + database"
t=$(date +%s)
( cd "$LOCAL/backend" && tar czf - data/VAL-* data/DEMO-* data/Case-113 spine.db 2>/dev/null ) \
  | "${SSH[@]}" "cd $REMOTE/backend && tar xzf -"
# Paths are stored absolute, so a copied database opens every study blank until
# the prefix is rewritten. The worklist looks right, which is what makes it
# confusing.
"${SSH[@]}" "cd $REMOTE/backend && python3 - <<'PY'
import sqlite3
src, dst = '$LOCAL/backend/', '$REMOTE/backend/'
c = sqlite3.connect('spine.db')
for t, cols in (('studies', ('volume_path','display_path')),
                ('series',  ('volume_path','display_path')),
                ('annotations', ('mask_path',))):
    for col in cols:
        c.execute(f'update {t} set {col}=replace({col},?,?)', (src, dst))
c.commit()
print('   rewrote stored paths')
PY"
secs $t

if [ "$WITH_REPLAY" = "--with-replay" ]; then
  step "5b · replay set (~8.2 GB, ~5 min)"
  t=$(date +%s)
  ( cd "$RESEARCH" && tar czf - rsna_preprocessed ) \
    | "${SSH[@]}" "cd /workspace && tar xzf -"
  "${SSH[@]}" "cd $REMOTE/backend && sed -i 's|^RETRAIN_REPLAY_DIR=.*|RETRAIN_REPLAY_DIR=/workspace/rsna_preprocessed|' .env && grep RETRAIN_REPLAY_DIR .env"
  secs $t
fi

step "6 · verify — refuse to call this done on a health check alone"
"${SSH[@]}" "supervisorctl restart spine_backend >/dev/null; sleep 10
cd $REMOTE/backend
echo -n '   checkpoint md5 : '; md5sum models/weights/phase2_cbam.pth | cut -d' ' -f1
echo -n '   spinenet .pt    : '; ls spinenet/weights/*/*.pt 2>/dev/null | wc -l
echo -n '   tss weights     : '; find ../tss-venv -name 'checkpoint_final.pth' 2>/dev/null | wc -l
echo -n '   torch GPU       : '; .venv/bin/python -c 'import torch; print(torch.cuda.is_available(), torch.__version__)' 2>/dev/null || echo 'torch not importable'
echo -n '   health          : '; curl -s -m 10 localhost:8000/health
echo
echo -n '   studies         : '; curl -s -m 15 localhost:8000/patients | python3 -c 'import json,sys; print(sum(len(p[\"studies\"]) for p in json.load(sys.stdin)))'
echo -n '   readiness       : '; curl -s -m 10 localhost:8000/retraining/readiness | python3 -c 'import json,sys; d=json.load(sys.stdin); print(\"holdout\", d[\"holdout_present\"], \"| replay\", d[\"replay_present\"])'"

echo ""
echo "══ done in $(( ($(date +%s) - T0) / 60 ))m $(( ($(date +%s) - T0) % 60 ))s ══"
cat <<EOF

Expected above: md5 $CKPT_MD5 · 4 .pt · 2 tss · torch GPU True ·
{"status":"ok"} · 12 studies.

A False on "torch GPU" is the one that looks harmless and is not: the box
keeps working, about ten times slower, and nothing errors. It happens when
the driver is older than the CUDA build pip served (requirements.txt pins no
torch); vast_setup.sh now refetches a matching build, so False here means
that fallback also failed.
Anything else means a step did not take -- re-run this script, it is idempotent.

From the laptop:
  ssh -fN -p $PORT -L 8000:localhost:8000 root@$HOST
  cd $LOCAL && ./run.sh frontend      # then http://localhost:5173

A full grading takes ~86 s on a 4090. Re-training needs --with-replay.
EOF
