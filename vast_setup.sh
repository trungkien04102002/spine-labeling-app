#!/bin/bash
# Vast.ai GPU setup for spine-labeling-app.
#
# Run it from INSIDE the cloned repo:
#   git clone https://<PAT>@github.com/trungkien04102002/spine-labeling-app.git
#   cd spine-labeling-app
#   ./vast_setup.sh                       # expects the checkpoint already placed
#   ./vast_setup.sh --gdrive-id <FILE_ID> # or auto-download it from Google Drive
#
# It installs backend deps, TotalSpineSeg (own venv) + weights, frontend deps,
# writes backend/.env (SQLite + CUDA seg), and verifies the grading checkpoint.
# See DEPLOY_VAST.md for the full picture + how to run/tunnel afterwards.
set -e

GDRIVE_ID=""
while [[ $# -gt 0 ]]; do
  case $1 in
    --gdrive-id) GDRIVE_ID="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; echo "Usage: $0 [--gdrive-id <checkpoint file id>]"; exit 1 ;;
  esac
done

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
CKPT="$REPO_DIR/backend/models/weights/phase2_cbam.pth"
CKPT_MD5="50101203903b1aa3bcf3d6103daa650e"

if [ ! -d "$REPO_DIR/backend" ]; then
  echo "ERROR: run this from the repo root (backend/ not found)."; exit 1
fi

echo "=== spine-labeling-app · Vast.ai setup ==="
echo "Repo: $REPO_DIR"
echo ""

# --- System packages -------------------------------------------------------
echo ">> Installing system packages…"
apt-get update
apt-get install -y git wget python3-venv nodejs npm

# --- Backend venv ----------------------------------------------------------
echo ">> Backend virtualenv + deps…"
cd "$REPO_DIR/backend"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gdown            # for optional checkpoint download

# --- Grading checkpoint ----------------------------------------------------
mkdir -p "$REPO_DIR/backend/models/weights"
if [ ! -f "$CKPT" ] && [ -n "$GDRIVE_ID" ]; then
  echo ">> Downloading grading checkpoint from Google Drive…"
  gdown "$GDRIVE_ID" -O "$CKPT"
fi
if [ ! -f "$CKPT" ]; then
  echo ""
  echo "!! Grading checkpoint missing: $CKPT"
  echo "   Download phase2_cbam.pth (243MB) from your Drive and place it there,"
  echo "   or re-run:  ./vast_setup.sh --gdrive-id <FILE_ID>"
  echo "   (setup will continue; the app won't grade until the file is present.)"
else
  GOT=$(md5sum "$CKPT" | awk '{print $1}')
  if [ "$GOT" = "$CKPT_MD5" ]; then
    echo ">> Checkpoint OK (md5 verified)."
  else
    echo "!! Checkpoint md5 mismatch: got $GOT, expected $CKPT_MD5 (re-copy the file)."
  fi
fi
deactivate

# --- TotalSpineSeg (own venv, pins numpy<2) --------------------------------
echo ">> TotalSpineSeg in its own venv + weights (~460MB)…"
cd "$REPO_DIR"
[ -d tss-venv ] || python3 -m venv tss-venv
source tss-venv/bin/activate
pip install --upgrade pip
pip install totalspineseg
totalspineseg_init
TSS_BIN="$REPO_DIR/tss-venv/bin/totalspineseg"
deactivate

# --- Frontend deps ---------------------------------------------------------
echo ">> Frontend deps…"
cd "$REPO_DIR/frontend"
npm install

# --- backend/.env ----------------------------------------------------------
echo ">> Writing backend/.env (SQLite + CUDA segmentation)…"
cat > "$REPO_DIR/backend/.env" <<EOF
MYSQL_DSN=sqlite:///./spine.db
TOTALSPINESEG_BIN=$TSS_BIN
SEG_DEVICE=cuda
EOF

# --- CUDA check ------------------------------------------------------------
echo ""
echo "=== CUDA check ==="
cd "$REPO_DIR/backend"; source .venv/bin/activate
python3 - <<EOF
import torch
print("torch", torch.__version__, "| CUDA available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
else:
    print("WARNING: no CUDA — seg will fall back slow; set SEG_DEVICE=cpu in backend/.env")
EOF
deactivate

# --- Done ------------------------------------------------------------------
cat <<EOF

=== Setup complete ===

Run (two shells on the VM):
  cd $REPO_DIR/backend && source .venv/bin/activate && uvicorn app.main:app --host 127.0.0.1 --port 8000
  cd $REPO_DIR/frontend && npm run dev

From your laptop, tunnel the ports and open http://localhost:5173 :
  ssh -p <PORT> -L 5173:localhost:5173 -L 8000:localhost:8000 root@<HOST>

Worklist starts empty — use "+ New study" then Upload an .mha/.nii.gz.
EOF
