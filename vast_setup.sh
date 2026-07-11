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
# It installs backend deps, TotalSpineSeg (own venv) + weights, frontend deps,
# writes backend/.env (SQLite + CUDA seg), and verifies the grading checkpoint.
# See DEPLOY_VAST.md for the full picture + how to run/tunnel afterwards.
set -e

# Default Google Drive bundle (spine-vm-upload/: weights/ + sample_volumes/).
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

# --- Download Drive bundle (checkpoint + sample volumes) -------------------
mkdir -p "$REPO_DIR/backend/models/weights"
if [ ! -f "$CKPT" ] && [ "$SKIP_DOWNLOAD" -eq 0 ]; then
  if [ -n "$GDRIVE_ID" ]; then
    echo ">> Downloading checkpoint (single file) from Google Drive…"
    gdown "$GDRIVE_ID" -O "$CKPT"
  elif [ -n "$GDRIVE_FOLDER_ID" ]; then
    echo ">> Downloading Drive bundle folder…"
    rm -rf /tmp/spine_bundle && mkdir -p /tmp/spine_bundle
    gdown --folder "https://drive.google.com/drive/folders/$GDRIVE_FOLDER_ID" \
      -O /tmp/spine_bundle || echo "   (folder download had issues — see fallback below)"
    # Place the checkpoint.
    FOUND=$(find /tmp/spine_bundle -name phase2_cbam.pth | head -1)
    [ -n "$FOUND" ] && cp "$FOUND" "$CKPT"
    # Stage sample volumes so they can be uploaded via the UI.
    mkdir -p "$REPO_DIR/sample_volumes"
    find /tmp/spine_bundle -name '*.mha' -exec cp {} "$REPO_DIR/sample_volumes/" \; 2>/dev/null || true
  fi
fi
if [ ! -f "$CKPT" ]; then
  echo ""
  echo "!! Grading checkpoint missing: $CKPT"
  echo "   The 243MB file may need Drive's virus-scan confirmation, which the"
  echo "   folder downloader can skip. Fix: share phase2_cbam.pth as its own file,"
  echo "   copy its FILE_ID, and re-run:  ./vast_setup.sh --gdrive-id <FILE_ID>"
  echo "   (setup continues; grading is disabled until the file is present.)"
else
  GOT=$(md5sum "$CKPT" | awk '{print $1}')
  if [ "$GOT" = "$CKPT_MD5" ]; then
    echo ">> Checkpoint OK (md5 verified)."
  else
    echo "!! Checkpoint md5 mismatch: got $GOT, expected $CKPT_MD5 (re-download)."
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

Worklist starts empty — use "+ New study" then Upload an .mha/.nii.gz
(sample volumes were staged in $REPO_DIR/sample_volumes/ if the bundle downloaded).
EOF
