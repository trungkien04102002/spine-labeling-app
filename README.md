# spine-labeling-app

A local web tool for a doctor to open a lumbar-spine MRI, review AI-generated
overlays (anatomy **segmentation** + per-disc abnormality **grading**), correct
them, and export the result. Built for LVTN Phase 3.

- **Backend** — FastAPI. Runs two independent models: TotalSpineSeg (anatomy
  labelmap) and a Phase-2 CBAM 3D-ResNet (per-disc grading, on crops the
  segmentation localizes). Stores metadata/annotations in a DB; MRI volumes and
  masks live on the filesystem.
- **Frontend** — React + Vite + Cornerstone3D. Patient-grouped worklist, 2D
  sagittal viewer with color segmentation overlay + editable grade table,
  mask brush editing, undo/redo, versioned save, and export.

## Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI, SQLAlchemy, SimpleITK, PyTorch |
| DB | MySQL (local dev) or SQLite (via `MYSQL_DSN`) |
| Segmentation | TotalSpineSeg CLI (separate venv — see below) |
| Frontend | React 19, Vite, Tailwind v4, Cornerstone3D |

---

## Quick start (local)

Prerequisites: Python 3.11, Node 18+, and MySQL running (or use SQLite — see
notes). TotalSpineSeg is installed separately (below).

```bash
# 1. Backend deps
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
deactivate

# 2. Frontend deps
cd ../frontend && npm install && cd ..

# 3. Grading checkpoint (243 MB, not in git)
#    place it at: backend/models/weights/phase2_cbam.pth

# 4. Point the backend at the TotalSpineSeg CLI (env or backend/.env)
export TOTALSPINESEG_BIN=/abs/path/to/totalspineseg-venv/bin/totalspineseg
export SEG_DEVICE=cpu          # or "cuda"

# 5. Run both
./run.sh                       # start   → http://localhost:5173
./run.sh logs                  # tail logs
./run.sh stop                  # stop
```

Open **http://localhost:5173**, create a study, upload an `.mha`/`.nii.gz`, then
**Run AI**.

### Running the servers by hand (instead of run.sh)

```bash
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload  # :8000
cd frontend && npm run dev                                                # :5173
```

---

## Segmentation (TotalSpineSeg)

Anatomy segmentation uses [TotalSpineSeg](https://github.com/neuropoly/totalspineseg).
It pins `numpy<2` and pulls in nnU-Net/torchio, which conflict with this
backend's torch/numpy, so it is **not** installed here — it runs as an external
CLI. Install it in its own environment:

```bash
python -m venv totalspineseg-venv && source totalspineseg-venv/bin/activate
pip install totalspineseg
totalspineseg_init            # downloads the pretrained nnU-Net weights (~460 MB)
```

Then set `TOTALSPINESEG_BIN` (+ `SEG_DEVICE`) as shown above. CPU segmentation
is ~10 min/volume; a CUDA GPU cuts it to ~1 min.

---

## Configuration (backend/.env or env vars)

| Var | Default | Notes |
|-----|---------|-------|
| `MYSQL_DSN` | `mysql+pymysql://root@localhost:3306/spine_labeling` | Use `sqlite:///./spine.db` to skip MySQL |
| `TOTALSPINESEG_BIN` | `totalspineseg` | Absolute path to the CLI |
| `SEG_DEVICE` | `cpu` | `cpu` or `cuda` (not `mps`) |
| `DATA_DIR` | `./data` | Where volumes/masks are stored |
| `INFERENCE_MODE` | `local` | `local` or `vast` (remote GPU server) |

---

## Deploy on a GPU VM (Vast.ai)

See **[DEPLOY_VAST.md](DEPLOY_VAST.md)**. Short version:

```bash
git clone https://github.com/trungkien04102002/spine-labeling-app.git
cd spine-labeling-app
./vast_setup.sh                # installs everything + downloads the model bundle
./run.sh                       # start both servers
```

From the laptop, tunnel the ports and open http://localhost:5173 :

```bash
ssh -p <PORT> -L 5173:localhost:5173 -L 8000:localhost:8000 root@<HOST>
```

---

## Tests

```bash
cd backend && source .venv/bin/activate
pytest -q -k "not end_to_end"        # unit/integration (SQLite in-memory)
RUN_SEG_TEST=1 pytest tests/test_seg.py   # opt-in heavy end-to-end seg
```

Frontend type-check: `cd frontend && npx tsc --noEmit`.

---

## Project layout

```
backend/
  app/
    routers/      studies (CRUD, upload, mask, export), patients, infer
    inference/    segmentation (TotalSpineSeg CLI), grading (CBAM), crops,
                  volume_io, local/remote backends
    models_db.py  patients, studies, annotations, correction_log
  models/weights/ phase2_cbam.pth   (grading checkpoint — not in git)
  data/           uploaded volumes + masks (not in git)
frontend/
  src/pages/      PatientList (worklist), Viewer
  src/components/Viewer/  CornerstoneViewport, GradeTable, Legend
serve_models.py   optional GPU model server for INFERENCE_MODE=vast
vast_setup.sh     one-shot VM setup      run.sh   start/stop both servers
```
