#!/bin/bash
# Vast.ai GPU setup for spine-labeling-app.
#
# Run it from INSIDE the cloned repo:
#   git clone https://github.com/trungkien04102002/spine-labeling-app.git
#   cd spine-labeling-app
#   ./vast_setup.sh                       # auto-downloads the Drive bundle
#   ./vast_setup.sh --gdrive-id <FILE_ID> # or point at a single checkpoint file
#   ./vast_setup.sh --skip-download       # checkpoint already placed by hand
#
# Installs backend deps, writes backend/.env (SQLite + CUDA seg), frontend deps,
# the grading checkpoint, and TotalSpineSeg (own venv). It is RESILIENT: a
# failure in one step (e.g. the heavy TotalSpineSeg install) does NOT abort the
# rest, and it is safe to re-run. A summary at the end lists what's OK/missing.
#
# NOTE: no `set -e` on purpose — steps are checked individually so the app can
# still boot even if the optional segmentation engine isn't ready yet.

GDRIVE_FOLDER_ID="1tBgdwA4f_1Ns4KWCf91Qi4zAB7PV0ixi"
GDRIVE_ID=""
SKIP_DOWNLOAD=0
while [[ $# -gt 0 ]]; do
  case $1 in
    --gdrive-id) GDRIVE_ID="$2"; shift 2 ;;
    --gdrive-folder-id) GDRIVE_FOLDER_ID="$2"; shift 2 ;;
    --skip-download) SKIP_DOWNLOAD=1; shift ;;
    *) echo "Unknown option: $1"; echo "Usage: $0 [--gdrive-id <file id>] [--gdrive-folder-id <id>] [--skip-download]"; exit 1 ;;
  esac
done

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
CKPT="$REPO_DIR/backend/models/weights/phase2_cbam.pth"
CKPT_MD5="50101203903b1aa3bcf3d6103daa650e"
TSS_BIN="$REPO_DIR/tss-venv/bin/totalspineseg"
WARN=()   # collected warnings for the final summary

if [ ! -d "$REPO_DIR/backend" ]; then
  echo "ERROR: run this from the repo root (backend/ not found)."; exit 1
fi

echo "=== spine-labeling-app · Vast.ai setup ==="
echo "Repo: $REPO_DIR"
echo ""

# --- System packages -------------------------------------------------------
echo ">> [1/6] System packages…"
apt-get update -y && apt-get install -y git wget python3-venv nodejs npm \
  || WARN+=("apt-get failed — install git/python3-venv/nodejs/npm manually")

# --- Backend venv ----------------------------------------------------------
echo ">> [2/6] Backend virtualenv + deps…"
cd "$REPO_DIR/backend"
[ -d .venv ] || python3 -m venv .venv
if ./.venv/bin/pip install --upgrade pip \
   && ./.venv/bin/pip install -r requirements.txt \
   && ./.venv/bin/pip install gdown; then
  echo "   backend deps OK"
else
  WARN+=("backend deps failed — the API will not start; check pip output above")
fi

# --- backend/.env (write EARLY so the app can boot regardless) -------------
echo ">> [3/6] Writing backend/.env (SQLite — no MySQL needed)…"
cat > "$REPO_DIR/backend/.env" <<EOF
MYSQL_DSN=sqlite:///./spine.db
TOTALSPINESEG_BIN=$TSS_BIN
SEG_DEVICE=cuda
EOF
echo "   wrote $REPO_DIR/backend/.env"

# --- Frontend deps ---------------------------------------------------------
echo ">> [4/6] Frontend deps…"
if (cd "$REPO_DIR/frontend" && npm install); then
  echo "   frontend deps OK"
else
  WARN+=("npm install failed — the frontend will not start")
fi

# --- Grading checkpoint ----------------------------------------------------
echo ">> [5/6] Grading checkpoint…"
mkdir -p "$REPO_DIR/backend/models/weights"
if [ ! -f "$CKPT" ] && [ "$SKIP_DOWNLOAD" -eq 0 ]; then
  GD="$REPO_DIR/backend/.venv/bin/gdown"
  [ -x "$GD" ] || GD="gdown"
  if [ -n "$GDRIVE_ID" ]; then
    echo "   downloading checkpoint (single file)…"
    "$GD" "$GDRIVE_ID" -O "$CKPT" || true
  elif [ -n "$GDRIVE_FOLDER_ID" ]; then
    echo "   downloading Drive bundle folder…"
    rm -rf /tmp/spine_bundle && mkdir -p /tmp/spine_bundle
    "$GD" --folder "https://drive.google.com/drive/folders/$GDRIVE_FOLDER_ID" -O /tmp/spine_bundle || true
    FOUND=$(find /tmp/spine_bundle -name phase2_cbam.pth | head -1)
    [ -n "$FOUND" ] && cp "$FOUND" "$CKPT"
    mkdir -p "$REPO_DIR/sample_volumes"
    find /tmp/spine_bundle -name '*.mha' -exec cp {} "$REPO_DIR/sample_volumes/" \; 2>/dev/null || true
  fi
fi
if [ ! -f "$CKPT" ]; then
  WARN+=("checkpoint missing ($CKPT) — grading disabled until placed; the 243MB file often needs Drive virus-scan confirmation, so re-run: ./vast_setup.sh --gdrive-id <FILE_ID>")
else
  GOT=$(md5sum "$CKPT" | awk '{print $1}')
  if [ "$GOT" = "$CKPT_MD5" ]; then echo "   checkpoint OK (md5 verified)"; \
  else WARN+=("checkpoint md5 mismatch: $GOT != $CKPT_MD5 (re-download)"); fi
fi

# --- TotalSpineSeg (own venv; optional, only needed for Run AI) ------------
echo ">> [6/6] TotalSpineSeg (own venv + weights ~460MB)…"
cd "$REPO_DIR"
[ -d tss-venv ] || python3 -m venv tss-venv
# nnunetv2 is a hard dep pip sometimes skips; install it explicitly. Pin torch
# <2.6: torch 2.6 flips torch.load(weights_only=True) by default, which breaks
# loading nnU-Net's checkpoints ("Unsupported global numpy...scalar").
if ./tss-venv/bin/pip install --upgrade pip \
   && ./tss-venv/bin/pip install totalspineseg "nnunetv2==2.4.2" \
        "torch==2.4.1" "torchvision==0.19.1" "torchaudio==2.4.1"; then
  if ./tss-venv/bin/totalspineseg_init; then
    echo "   TotalSpineSeg ready"
  else
    WARN+=("totalspineseg_init failed — run it later: ./tss-venv/bin/totalspineseg_init")
  fi
else
  WARN+=("TotalSpineSeg install failed — segmentation (Run AI) won't work until fixed")
fi

# --- CUDA check ------------------------------------------------------------
echo ""
echo "=== CUDA check ==="
"$REPO_DIR/backend/.venv/bin/python" - <<'EOF' 2>/dev/null || echo "(torch not importable yet)"
import torch
print("torch", torch.__version__, "| CUDA available:", torch.cuda.is_available())
print("GPU:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none — set SEG_DEVICE=cpu in backend/.env")
EOF

# --- Summary ---------------------------------------------------------------
echo ""
echo "=== Setup summary ==="
if [ ${#WARN[@]} -eq 0 ]; then
  echo "  ✓ everything installed"
else
  echo "  Some steps need attention:"
  for w in "${WARN[@]}"; do echo "   - $w"; done
fi
cat <<EOF

Run it:
  ./run.sh both          # backend :8000 + frontend :5173
  ./run.sh stop          # stop

From your laptop, tunnel both ports and open http://localhost:5173 :
  ssh -p <PORT> -L 5173:localhost:5173 -L 8000:localhost:8000 root@<HOST>

Worklist starts empty — "+ New study" then Upload an .mha/.nii.gz
(sample volumes staged in $REPO_DIR/sample_volumes/ if the bundle downloaded).
EOF
