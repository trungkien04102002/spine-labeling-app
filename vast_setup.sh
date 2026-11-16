#!/bin/bash
# GPU box setup for spine-labeling-app (Ubuntu + NVIDIA, as root).
#
# Run it from INSIDE the cloned repo:
#   git clone https://github.com/trungkien04102002/spine-labeling-app.git
#   cd spine-labeling-app
#   ./vast_setup.sh                       # downloads weights from the GitHub Release
#   ./vast_setup.sh --skip-download       # weights already placed (deploy_box.sh)
#
# Works on any Ubuntu box with an NVIDIA GPU where you are root (Vast.ai or
# not). Installs backend deps, writes backend/.env (SQLite + CUDA seg),
# frontend deps, the model weights + sample cases, and TotalSpineSeg (own venv). It is RESILIENT: a
# failure in one step (e.g. the heavy TotalSpineSeg install) does NOT abort the
# rest, and it is safe to re-run. A summary at the end lists what's OK/missing.
#
# NOTE: no `set -e` on purpose — steps are checked individually so the app can
# still boot even if the optional segmentation engine isn't ready yet.

SKIP_DOWNLOAD=0
while [[ $# -gt 0 ]]; do
  case $1 in
    --skip-download) SKIP_DOWNLOAD=1; shift ;;
    *) echo "Unknown option: $1"; echo "Usage: $0 [--skip-download]"; exit 1 ;;
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

echo "=== spine-labeling-app · GPU box setup ==="
echo "Repo: $REPO_DIR"
echo ""

# --- System packages -------------------------------------------------------
echo ">> [1/6] System packages…"
# Node only when missing: a NodeSource nodejs (bundles npm) conflicts with
# Ubuntu's npm package, and Ubuntu's own nodejs is too old for Vite anyway.
PKGS="git wget python3-venv"
command -v node >/dev/null 2>&1 || PKGS="$PKGS nodejs npm"
apt-get update -y && apt-get install -y $PKGS \
  || WARN+=("apt-get failed — install $PKGS manually")
NODE_MAJOR=$(node -v 2>/dev/null | sed 's/^v\([0-9]*\).*/\1/')
[ "${NODE_MAJOR:-0}" -ge 20 ] \
  || WARN+=("Node ${NODE_MAJOR:-missing} is too old for the frontend build -- install Node 22 (docs/DEPLOY_GPU.md)")

# --- Backend venv ----------------------------------------------------------
echo ">> [2/6] Backend virtualenv + deps…"
cd "$REPO_DIR/backend"
[ -d .venv ] || python3 -m venv .venv
if ./.venv/bin/pip install --upgrade pip \
   && ./.venv/bin/pip install -r requirements.txt; then
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
  # The trigger imports torchvision too. Asking torch alone misses the state
  # where torch is right and torchvision is not: cuda_is_available() answers
  # True and the refetch never runs, while the first grading dies on import.
  if ! ./.venv/bin/python -c 'import sys, torch, torchvision
from torchvision.ops import nms
sys.exit(0 if torch.cuda.is_available() else 1)' 2>/dev/null; then
    DRIVER_CUDA=$(nvidia-smi | grep -oE 'CUDA Version: [0-9]+\.[0-9]+' | awk '{print $3}' | head -1)
    CU_TAG="cu$(echo "${DRIVER_CUDA:-}" | tr -d '.')"
    echo "   torch reports no GPU; driver supports CUDA ${DRIVER_CUDA:-?} → refetching $CU_TAG"
    # torchvision must come from the same index: its compiled ops link against
    # one torch build, and pip leaves the installed wheel alone because the
    # version still "satisfies" the requirement. The mismatch stays silent
    # until something imports it, then raises "operator torchvision::nms does
    # not exist" -- so force it, and IMPORT it in the check below.
    # torch.cuda.is_available() answers True over a broken torchvision.
    # Name the exact +cuNNN version. Plain "torch" is reported as already
    # satisfied by the wheel that is there -- pip compares versions, and
    # 2.14.0 and 2.14.0+cu126 only differ once the local tag is spelled out.
    # This is the same trap as torchvision below, in the other direction.
    TORCH_VER=$(./.venv/bin/python -c 'import torch; print(torch.__version__.split("+")[0])' 2>/dev/null)
    if [ -n "$DRIVER_CUDA" ] && [ -n "$TORCH_VER" ] \
       && ./.venv/bin/pip install -q \
            --index-url "https://download.pytorch.org/whl/$CU_TAG" \
            "torch==${TORCH_VER}+${CU_TAG}" 2>/dev/null \
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

# --- Model weights (GitHub Release, md5-checked) ---------------------------
echo ">> [5/6] Model weights (tools/fetch_assets.py)…"
if [ "$SKIP_DOWNLOAD" -eq 0 ]; then
  python3 "$REPO_DIR/tools/fetch_assets.py" all \
    || WARN+=("weight download failed -- re-run: python3 tools/fetch_assets.py")
fi
if [ ! -f "$CKPT" ]; then
  WARN+=("checkpoint missing ($CKPT) -- run: python3 tools/fetch_assets.py models")
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

# --- What grading needs, and what only re-training needs -------------------
# SpineNet weights come with tools/fetch_assets.py above; without them grading
# dies three stages in with "save path .../detect-vfr could not be found".
# The frozen held-out set (backend/data/holdout_frozen) is RSNA-derived, so it
# is not published; only /admin's re-training evaluation needs it.
SPINENET_PT=$(ls "$REPO_DIR"/backend/spinenet/weights/*/*.pt 2>/dev/null | wc -l)
if [ "$SPINENET_PT" -lt 4 ]; then
  WARN+=("SpineNet weights incomplete ($SPINENET_PT/4 .pt files) -- run: python3 tools/fetch_assets.py models")
else
  echo "   SpineNet weights OK (4 .pt files)"
fi
if [ ! -f "$REPO_DIR/backend/data/holdout_frozen/train_metadata.csv" ]; then
  echo "   (no frozen held-out set: fine unless you re-train from /admin, see README)"
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

Check it end to end (uploads a SPIDER volume and grades it):
  tools/check.sh --gpu
EOF
