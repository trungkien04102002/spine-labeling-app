# Deploy on a Vast.ai GPU box

Run the whole app (backend + frontend + models) on the GPU VM, then SSH-tunnel
the ports back to your laptop and use it in your local browser. GPU cuts
TotalSpineSeg from ~10 min/volume (CPU) to ~1 min (CUDA).

Placeholders: `<HOST>` and `<PORT>` are the Vast SSH host/port (from the
instance's "Connect" panel, e.g. `ssh -p 12345 root@ssh5.vast.ai`).

## What the VM is missing

Two weight stores are **not** in git (too big / gitignored):

1. **Grading checkpoint** `backend/models/weights/phase2_cbam.pth` (243 MB) —
   copy from the laptop (md5 `50101203903b1aa3bcf3d6103daa650e`).
2. **TotalSpineSeg weights** (~460 MB) — do NOT copy; `totalspineseg_init`
   downloads them on the VM.

The DB is created automatically on startup. `backend/data/` (uploaded volumes)
is excluded, so the VM starts with an empty worklist.

---

## 1. Get the code onto the VM (laptop)

### Option A — git clone (recommended)

The code lives in a **private** GitHub repo:
`git@github.com:trungkien04102002/spine-labeling-app.git`. On the VM you need
credentials to clone it — the simplest is a GitHub Personal Access Token
(Settings → Developer settings → Fine-grained token, read-only, this repo):

```bash
cd /workspace
git clone https://<YOUR_PAT>@github.com/trungkien04102002/spine-labeling-app.git
# (or, if the VM's SSH key is added to your GitHub account:)
# git clone git@github.com:trungkien04102002/spine-labeling-app.git
```

### Option B — rsync (no GitHub needed)

```bash
rsync -avz -e "ssh -p <PORT>" \
  --exclude node_modules --exclude .venv --exclude backend/data \
  --exclude __pycache__ --exclude '*.pth' --exclude '*.db' \
  /Users/kienha/spine-labeling-app/ root@<HOST>:/workspace/spine-labeling-app/
```

### Then copy the grading checkpoint (both options)

The checkpoint is gitignored, so it is **never** cloned/rsynced — copy it
directly from the laptop:

```bash
scp -P <PORT> \
  /Users/kienha/spine-labeling-app/backend/models/weights/phase2_cbam.pth \
  root@<HOST>:/workspace/spine-labeling-app/backend/models/weights/
```

## 2. Install on the VM (over SSH)

```bash
ssh -p <PORT> root@<HOST>
apt-get update && apt-get install -y python3-venv nodejs npm

# Backend deps (torch pulls the CUDA build on a GPU box)
cd /workspace/spine-labeling-app/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
deactivate

# TotalSpineSeg in its OWN venv (it pins numpy<2, conflicts with the backend)
cd /workspace
python3 -m venv tss-venv && source tss-venv/bin/activate
pip install totalspineseg && totalspineseg_init      # downloads ~460 MB
deactivate
```

Verify the checkpoint arrived intact:

```bash
md5sum /workspace/spine-labeling-app/backend/models/weights/phase2_cbam.pth
# -> 50101203903b1aa3bcf3d6103daa650e
```

## 3. Run backend + frontend (VM, two shells)

Backend — SQLite (no MySQL needed) + GPU segmentation:

```bash
cd /workspace/spine-labeling-app/backend && source .venv/bin/activate
export MYSQL_DSN="sqlite:///./spine.db"
export TOTALSPINESEG_BIN=/workspace/tss-venv/bin/totalspineseg
export SEG_DEVICE=cuda
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd /workspace/spine-labeling-app/frontend
npm install
npm run dev            # serves on :5173
```

## 4. Tunnel the ports to the laptop (laptop)

```bash
ssh -p <PORT> -L 5173:localhost:5173 -L 8000:localhost:8000 root@<HOST>
```

Keep that SSH session open, then open **http://localhost:5173** in the laptop
browser. The frontend calls `localhost:8000`, which the tunnel forwards to the
VM's backend — no CORS/host config needed.

## 5. First use

The VM worklist starts empty. Click **+ New study**, then **Upload** an MRI
(`.mha` / `.nii.gz`). To reuse a local sample:

```bash
scp -P <PORT> /Users/kienha/spinet-v2/spider/images/100_t2.mha \
  root@<HOST>:/tmp/     # then upload it via the UI
```

Then **Run AI** → seg + grading run on the GPU (~1 min).

## Notes

- Vast instances are ephemeral: `/workspace` usually persists across
  stop/start, but re-verify the weights after a restart.
- If `pip install torch` grabs a CPU build, install the CUDA wheel that matches
  the box's CUDA (see pytorch.org), then `SEG_DEVICE=cuda`.
- To expose publicly instead of tunneling, run uvicorn/vite with `--host
  0.0.0.0` and map the ports in Vast — but the tunnel is simpler and safer.
