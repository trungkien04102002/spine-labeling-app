# spine-labeling-app

A web tool for reading lumbar-spine MRI with AI help. A clinician uploads a
sagittal scan; the app segments the spine, grades every lumbar disc for 11
degenerative findings, and shows both on the image. The clinician can correct
the grades and the segmentation, and those corrections are kept as feedback
for re-training.

This is the software part of the master's thesis *"AI-Assisted Medical Image
Annotation for Low Back Pain"* (HCMUT, 2026). The grading model was trained in
a separate repository, see [Related repositories](#related-repositories).

AI agents: read [AGENTS.md](AGENTS.md) first.

## Contents

- [How it works](#how-it-works)
- [Quick start, no GPU (about 10 minutes)](#quick-start-no-gpu)
- [Grading new scans (GPU recommended)](#grading-new-scans)
- [Checking that everything works](#checking-that-everything-works)
- [Deploying for other people](#deploying-for-other-people)
- [Configuration](#configuration)
- [Optional parts](#optional-parts)
- [Project layout](#project-layout)
- [Related repositories](#related-repositories)

## How it works

```
upload (.zip of DICOM, .nii.gz, .mha)
   │
   ▼
TotalSpineSeg ──► segmentation mask (vertebrae, discs, canal)
   │
   ▼
SpineNet (Oxford) ──► finds and labels discs L1-L2 … L5-S1,
   │                  grades 8 findings (Pfirrmann, herniation, …)
   ▼
Model A (this thesis, 3D ResNet34 + CBAM) ──► grades canal stenosis
   │                                         and left/right foraminal stenosis
   ▼
11 findings per disc ──► viewer: image + mask + editable table
                                   │
                                   ▼
                        corrections ──► /admin: batch, re-train,
                                        review, activate a new model
```

| Part | Tech |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy (SQLite by default), PyTorch |
| Frontend | React 19, Vite, Tailwind 4, Cornerstone3D (WebGL viewer) |
| Segmentation | [TotalSpineSeg](https://github.com/neuropoly/totalspineseg) CLI in its own venv |
| Grading | vendored [SpineNet](https://github.com/rwindsor1/SpineNet) + model A |

The interface is Vietnamese by default (it was built for Vietnamese
radiologists) and has an English toggle (VI/EN, top right). Code, comments and
these docs are in English. Switch the UI to English with the **VI/EN** toggle
before following the steps below; button names here are the English ones.

## Quick start, no GPU

You get the app running with one SPIDER scan that has already been graded, so
you can look around without installing the models.

Needs Python 3.11, Node 22 (20.19+ works; Vite 8 refuses older) and git. Tested on macOS and Ubuntu.

```bash
git clone https://github.com/trungkien04102002/spine-labeling-app.git
cd spine-labeling-app

# backend
python3.11 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
cp backend/.env.example backend/.env

# frontend
(cd frontend && npm install)

# sample scans + one graded case (~40 MB, from the GitHub Release)
python3 tools/fetch_assets.py demo
backend/.venv/bin/python tools/demo_case.py import sample_volumes/demo_case.zip

./run.sh            # backend :8000 + frontend :5173   (./run.sh stop to stop)
```

If `pip`, `npm` or `fetch_assets.py` fail with `CERTIFICATE_VERIFY_FAILED`,
the network inspects TLS (common on company networks). Export a CA bundle that
includes the proxy's root certificate and point the tools at it, e.g. on
macOS:

```bash
security find-certificate -a -p /Library/Keychains/System.keychain \
  /System/Library/Keychains/SystemRootCertificates.keychain > ~/ca.pem
export SSL_CERT_FILE=~/ca.pem PIP_CERT=~/ca.pem NODE_EXTRA_CA_CERTS=~/ca.pem
```

Open http://localhost:5173:

1. Under **Create my room**, type a name and a 4-digit PIN
   twice. A room keeps one clinician's cases and edits apart from everyone
   else's; the PIN only stops people walking into the wrong room by mistake.
2. Under **Sample cases to try**, add `SAMPLE-SPIDER-100`,
   then press **Open →**.
3. You see the sagittal MRI with the coloured segmentation, a summary of
   findings on the right, and the 11-finding table below. Change a grade or
   paint on the mask to see how corrections are recorded.

`/admin` is the operator page (rooms, corrections, re-training, model
versions). With `ADMIN_PASSWORD` empty it opens without a password.

## Grading new scans

Grading needs three more things: the model weights, TotalSpineSeg, and ideally
an NVIDIA GPU. One scan takes about 1 minute on a GPU (RTX 3060 or better,
~1.5 GB GPU memory) and 10+ minutes on a laptop CPU.

```bash
# 1. weights: model A + SpineNet (~1.1 GB, md5-checked)
python3 tools/fetch_assets.py models

# 2. TotalSpineSeg in its own venv (it pins numpy<2, which clashes with the backend)
python3.11 -m venv ~/totalspineseg-venv
~/totalspineseg-venv/bin/pip install "totalspineseg==20250416" "nnunetv2==2.4.2" \
    "torch==2.4.1" "torchvision==0.19.1"
~/totalspineseg-venv/bin/totalspineseg_init        # downloads its weights (~460 MB)

# 3. tell the backend where it is, in backend/.env
#    TOTALSPINESEG_BIN=/home/<you>/totalspineseg-venv/bin/totalspineseg
#    SEG_DEVICE=cuda        (or cpu)

./run.sh
```

Then in the app: **+ New study**, upload a scan, open it and press
**Run AI grading**. The segmentation appears first,
the grades a few seconds later.
Use a `.zip` of a DICOM series or a single `.nii.gz` / `.mha`. The AI reads the
**sagittal** series (T2 preferred); axial series are shown but not graded.
`sample_volumes/` has three SPIDER scans to try.

On a fresh Ubuntu GPU server, `./vast_setup.sh` does all of the above in one
go, see [docs/DEPLOY_GPU.md](docs/DEPLOY_GPU.md).

## Model weights and sample files

Large files are not in git. They are attached to the GitHub Release
[`assets-v1`](https://github.com/trungkien04102002/spine-labeling-app/releases/tag/assets-v1)
and `tools/fetch_assets.py` downloads them to the right place and checks
their md5 (`demo` = the sample files only, `models` = the weights only, no
argument = everything).

| File | What it is | Size | Goes to |
|---|---|---|---|
| `phase2_cbam.pth` | Model A: 3D ResNet34 + CBAM, trained in spinet-v2 (see its `TRAINING.md`) | 255 MB | `backend/models/weights/` |
| `spinenet_weights.tar` | Upstream SpineNet (Oxford VGG): disc detection, labelling, 8 findings | 822 MB | `backend/spinenet/weights/` |
| `sample_volumes.zip` | Three SPIDER sagittal T2 scans (CC BY 4.0) to upload | 16 MB | `sample_volumes/` |
| `demo_case.zip` | SPIDER case 100, already graded (for the no-GPU quick start) | 14 MB | `sample_volumes/` |

Not on the Release: TotalSpineSeg's weights (its own `totalspineseg_init`
downloads them) and the optional model B (see below).

## Checking that everything works

```bash
tools/check.sh          # backend tests + frontend lint and build (~2 min, no GPU)
tools/check.sh --gpu    # + uploads sample_volumes/100_t2.mha and grades it via the API
```

`check.sh` builds the frontend into a temporary folder, so running it on a
server does not replace the `frontend/dist` that server is serving.
The backend tests use an in-memory SQLite database; tests that need data not
in the repo (RSNA, TotalSpineSeg runs) skip themselves. `--gpu` starts the
backend if it is not already running and prints `SMOKE OK` with the graded
levels; the result is then visible in the UI in the room `__smoke`.

## Deploying for other people

See [docs/DEPLOY_GPU.md](docs/DEPLOY_GPU.md): one GPU server serving the API
and the built frontend on a single port. [DEPLOY_VAST.md](DEPLOY_VAST.md) is
the detailed runbook used for the clinician trial on rented Vast.ai machines.
`tools/deploy_box.sh <port> <host>` sets such a box up from your own machine
in one command; note that it copies your working tree (`rsync --delete`), your
local `backend/spine.db` and every room's studies (`backend/data/p*-*`) to
the box, which is what the trial wanted but not always what you want.

## Configuration

All settings are environment variables or lines in `backend/.env`; see
[backend/.env.example](backend/.env.example) and `backend/app/config.py`.

| Variable | Default | What it does |
|---|---|---|
| `MYSQL_DSN` | `sqlite:///./spine.db` | Database (any SQLAlchemy URL) |
| `DATA_DIR` | `./data` | Uploaded scans, masks and results (`backend/data/<study>/`) |
| `TOTALSPINESEG_BIN` | `totalspineseg` | Path to the TotalSpineSeg CLI |
| `SEG_DEVICE` | `cpu` | `cpu` or `cuda` for segmentation |
| `GRADING_DEVICE` | `auto` | GPU for SpineNet + model A when available |
| `ADMIN_PASSWORD` | empty | Locks `/admin`; set it on any shared server |
| `FRONTEND_DIST` | empty | Built frontend served by the backend |
| `VIEW_ONLY` | `false` | Trial mode: no edits, no AI runs |
| `SURVEY_FORM_URL` | empty | Trial mode: external survey instead of the in-app one |
| `SAMPLE_STUDIES` | `VAL-*,SAMPLE-*` | Which unowned studies rooms may copy in |
| `RETRAIN_REPLAY_DIR` | empty | Original training discs for re-training |
| `INFERENCE_MODE` | `local` | `vast` sends inference to `serve_models.py` on another machine |
| `VAST_URL` | empty | Address of that `serve_models.py` server (with `INFERENCE_MODE=vast`) |
| `CORS_ORIGINS` | empty | Extra browser origins allowed to call the API (comma-separated); the Vite dev server is always allowed |

Frontend: `VITE_API_URL` (default `http://localhost:8000`; empty means "same
origin as the page", used when the backend serves the frontend).

## Optional parts

**Trial mode.** Used for the clinician evaluation (Oct 2026). Rooms, PINs, the
personal room links `/admin` can send (`/?phong=<code>`) and the survey
(★ button) are always there. Two settings are for a trial server and off by
default: `VIEW_ONLY=true` for a server where clinicians only look at graded
cases, and `SURVEY_FORM_URL` for a Google Form instead of the in-app survey
(`tools/google_form/` builds it).

**Feedback loop and re-training.** Corrections are queued, not applied: in
`/admin` they are sealed into a batch, a re-training run fine-tunes model A's
heads on them and produces a *candidate*, and a person activates it in
`/admin/models`. So a correction never changes another patient's result on
its own. Re-training mixes in ~200 original discs so the model does not
drift; those come from the RSNA data prepared in `spinet-v2` (`rsna_preprocessed`, ~8.2 GB,
set `RETRAIN_REPLAY_DIR`). Evaluating a run also needs a frozen hold-out set in
`backend/data/holdout_frozen/` (RSNA-derived, so not published; only its
`MANIFEST.json` is in git). Rebuild it from the same data with
`cd backend && .venv/bin/python -m app.feedback.freeze_holdout --source-dir <spinet-v2>/rsna_preprocessed --out-dir data/holdout_frozen --split-seed 42`
(`--split-seed 42` keeps it to patients model A did not train on). Without them
`/admin` shows re-training as blocked and says why. A GPU is strongly
recommended (CPU: ~14 min per epoch).

**Model B (comparison model).** A MedCLIP classifier from the research group
([JIT-Web](https://github.com/harbinger-ux/JIT-Web)), shown next to model A
during part of the trial and later hidden. Its weights are not distributed
here; build them with `tools/build_reference_b.py` (instructions in its
docstring), then switch it on in `/admin`. The app works the same without it.

## Project layout

```
backend/
  app/
    main.py            FastAPI app, routers, static frontend
    config.py          every setting (see Configuration)
    models_db.py       readers (rooms), patients, studies, series, annotations, corrections
    routers/           studies + upload, full_grading (async jobs), feedback,
                       retraining, admin, survey, readers, trial export, reference_b
    inference/         volume_io (DICOM/NIfTI/MHA), segmentation (TotalSpineSeg CLI),
                       spinenet_grading, grading (model A), full_grading (merges both)
    feedback/          correction batches, frozen hold-out, re-training, model registry
  models/              model A architecture; weights/ (not in git; ACTIVE names the live one)
  spinenet/            vendored upstream SpineNet; weights/ not in git
  tests/               pytest, ~200 tests
frontend/src/
  pages/               Join (room), PatientList (worklist), Viewer, Survey, Admin*, ModelVersions
  components/Viewer/   CornerstoneViewport (WebGL), GradeTable, FindingsSummary, …
  lib/                 api.ts (every backend call), strings.vi.ts (Vietnamese UI text)
tools/
  fetch_assets.py      download weights + sample cases from the Release
  demo_case.py         export / import a graded study as a shared sample
  check.sh, smoke_grade.py   the checks above
  deploy_box.sh, deploy_view_only.sh   one-command Vast.ai deploys
  build_reference_b.py model B (optional)
  diagnose_viewer.mjs  headless browser check of the viewer (black-image bugs)
run.sh                 start / stop backend + frontend
vast_setup.sh          set up an Ubuntu GPU server (Vast.ai or not)
serve_models.py        optional remote inference server (INFERENCE_MODE=vast)
```

## Related repositories

- **[spinet-v2](https://github.com/trungkien04102002/spinet-v2)**: research
  code. Data preparation, training and evaluation of model A (RSNA 2024 and
  SPIDER). Read its `TRAINING.md` to re-train; the result is the
  `phase2_cbam.pth` this app loads.
- [SpineNet](https://github.com/rwindsor1/SpineNet) (Oxford VGG): vendored in
  `backend/spinenet/`.
- [TotalSpineSeg](https://github.com/neuropoly/totalspineseg): segmentation.

Datasets: [SPIDER](https://doi.org/10.5281/zenodo.10159290) (sample scans,
CC BY 4.0) and [RSNA 2024 Lumbar Spine](https://www.kaggle.com/competitions/rsna-2024-lumbar-spine-degenerative-classification)
(training; download it yourself from Kaggle).
