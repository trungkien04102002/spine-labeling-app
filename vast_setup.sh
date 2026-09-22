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

# requirements.txt pins no torch, so pip serves whichever CUDA build is current
# on PyPI -- cu130 as of 2026-09. A box whose driver only reaches 12.6 imports
# that wheel happily and reports no GPU, and everything downstream keeps working
# on the CPU roughly ten times slower. Nothing errors, so it is invisible.
# Detect it and refetch the build this driver can actually run.
if [ -x ./.venv/bin/python ] && command -v nvidia-smi >/dev/null 2>&1    && nvidia-smi -L >/dev/null 2>&1; then
  if ! ./.venv/bin/python -c 'import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)' 2>/dev/null; then
    DRIVER_CUDA=$(nvidia-smi | grep -oE 'CUDA Version: [0-9]+\.[0-9]+' | awk '{print $3}' | head -1)
    CU_TAG="cu$(echo "${DRIVER_CUDA:-}" | tr -d '.')"
    echo "   torch reports no GPU; driver supports CUDA ${DRIVER_CUDA:-?} → refetching $CU_TAG"
    # torchvision must come from the same index: its compiled ops link against
    # one torch build, and pip leaves the installed wheel alone because the
    # version still "satisfies" the requirement. The mismatch stays silent
    # until something imports it, then raises "operator torchvision::nms does
    # not exist" -- so force it, and IMPORT it in the check below.
    # torch.cuda.is_available() answers True over a broken torchvision.
    if [ -n "$DRIVER_CUDA" ] \
       && ./.venv/bin/pip install -q \
            --index-url "https://download.pytorch.org/whl/$CU_TAG" torch 2>/dev/null \
       && ./.venv/bin/pip install -q --force-reinstall --no-deps \
            --index-url "https://download.pytorch.org/whl/$CU_TAG" torchvision 2>/dev/null \
       && ./.venv/bin/python -c 'import sys, torch, torchvision
from torchvision.ops import nms
sys.exit(0 if torch.cuda.is_available() else 1)'; then
      echo "   torch + torchvision now see the GPU ($CU_TAG)"
    else
      WARN+=("torch cannot use this GPU (driver CUDA ${DRIVER_CUDA:-unknown}); grading will run on CPU")
    fi
  fi
fi

# --- backend/.env (write EARLY so the app can boot regardless) -------------
echo ">> [3/6] Writing backend/.env (SQLite — no MySQL needed)…"
cat > "$REPO_DIR/backend/.env" <<EOF
MYSQL_DSN=sqlite:///./spine.db
TOTALSPINESEG_BIN=$TSS_BIN
SEG_DEVICE=cuda
# Re-training from /admin mixes ~200 ORIGINAL discs in so the heads do not
# forget. That set is rsna_preprocessed from the research repo (~8.2 GB) and is
# NOT copied to this box, so the setting is left empty on purpose: /admin then
# shows the run as blocked, with the reason, instead of running the weaker
# replay-free experiment by accident. Point it at a copy to enable runs here.
RETRAIN_REPLAY_DIR=
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
   && ./tss-venv/bin/pip install "totalspineseg==20250416" "nnunetv2==2.4.2" \
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

# --- Data this script cannot fetch ----------------------------------------
# Neither of these travels with the code: backend/spinenet/weights/ and
# backend/data/ are both gitignored. The script cannot download them either --
# the SpineNet weights are 685MB from robots.ox.ac.uk (slow, and it has failed
# mid-transfer), and the frozen held-out set only exists on the laptop that
# froze it. Copy both from there. Without the first, grading dies three stages
# in with "save path .../detect-vfr could not be found"; without the second,
# /admin cannot evaluate anything.
echo ">> checking data that must be copied from the laptop…"
SPINENET_PT=$(ls "$REPO_DIR"/backend/spinenet/weights/*/*.pt 2>/dev/null | wc -l)
if [ "$SPINENET_PT" -lt 4 ]; then
  WARN+=("SpineNet weights incomplete ($SPINENET_PT/4 .pt files in backend/spinenet/weights/) — grading will fail at the SpineNet stage. From the laptop: cd backend/spinenet && tar czf - weights | ssh <BOX> 'tar xzf - -C /workspace/spine-labeling-app/backend/spinenet'")
else
  echo "   SpineNet weights OK (4 .pt files)"
fi
if [ ! -f "$REPO_DIR/backend/data/holdout_frozen/train_metadata.csv" ]; then
  WARN+=("frozen held-out set missing (backend/data/holdout_frozen) — /admin cannot evaluate a re-training run. From the laptop: cd backend && tar czf - data/holdout_frozen | ssh <BOX> 'cd /workspace/spine-labeling-app/backend && tar xzf -'")
else
  echo "   frozen held-out set OK"
fi

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
