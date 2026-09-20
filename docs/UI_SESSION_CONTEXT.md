# Context for a UI-only session

Self-contained briefing for working on this app's interface without the thesis
research context loaded. Written 2026-09-20.

Read this first, then `HUONG_DAN.md` (how to run) and `DEPLOY_VAST.md` (GPU box).

---

## 1. What the thesis is, in one paragraph

Master's thesis: *Ứng dụng AI trong gán nhãn ảnh y tế cho bệnh đau thắt lưng*
(HCMUT, advisor Phan Trọng Nhân). It grades lumbar-spine MRI for degenerative
findings. The research half lives in a **different repo**
(`/Users/kienha/spinet-v2`) and trains the grading models. **This repo is the
software half**: the tool a radiologist would actually use.

The app is a thesis deliverable in its own right, not a demo. Its specific
claim is the **doctor-feedback loop**: the model proposes grades, the doctor
corrects them, corrections are queued as expert feedback, retraining happens
offline, and a new model version must be reviewed before it goes live.

## 2. Why the feedback loop is designed the way it is

This is the one design decision to understand before changing anything in the
Viewer.

A doctor's correction does **not** change the model immediately. It is queued.
Retraining is a separate, deliberate step — `/admin` can start one on a sealed
batch (`POST /corrections/batches/{id}/retrain`, a polled job), and it produces
a *candidate* checkpoint at most. A new checkpoint has to be activated
deliberately.
The reason is stated in the UI itself: otherwise patient B's result could
change because of a correction made on patient A, which is unacceptable in a
clinical tool. If a UI change makes corrections look instant, it breaks the
claim the thesis makes about this app.

## 3. The 11 labels, and where each comes from

The grading table mixes **two** model sources. This surprises people.

| Label | Source |
|---|---|
| `canal_stenosis` | the thesis's fine-tuned CBAM model |
| `left_foraminal` | the thesis's fine-tuned CBAM model |
| `right_foraminal` | the thesis's fine-tuned CBAM model |
| `pfirrmann` | vendored upstream SpineNet |
| `disc_narrowing` | vendored upstream SpineNet |
| `spondylolisthesis` | vendored upstream SpineNet |
| `upper_endplate_defect` | vendored upstream SpineNet |
| `lower_endplate_defect` | vendored upstream SpineNet |
| `upper_marrow` | vendored upstream SpineNet |
| `lower_marrow` | vendored upstream SpineNet |
| `disc_herniation` | vendored upstream SpineNet |

Merge logic: `backend/app/inference/full_grading.py::merge_gradings`.
Upstream also emits its own `canal_stenosis` / `left_foraminal` /
`right_foraminal`, and those are **dropped** at merge in favour of the thesis
model's. Do not "fix" that by showing both.

## 4. Layout

```
frontend/src/                       2452 lines total
  App.tsx                     14    two routes: "/" and "/viewer/:studyId"
  main.tsx                    13
  index.css                   21
  pages/
    PatientList.tsx          442    worklist: patients, studies, upload, delete
    Viewer.tsx               759    the main screen; owns nearly all state
  components/Viewer/
    CornerstoneViewport.tsx  548    the MRI canvas (Cornerstone3D, WebGL)
    GradeTable.tsx           203    the editable 11-label table
    Legend.tsx                47    segmentation colour legend
  lib/
    api.ts                   315    every backend call, typed
    cornerstone.ts            22    Cornerstone init
    history.ts                68    undo/redo for mask edits
```

`Viewer.tsx` holds the state for the whole screen (about 16 `useState` hooks:
study detail, series list, grading result, corrections queue, job polling,
dirty flags, target slice). Anything visual is likely reachable from there.

Backend is ~3900 lines under `backend/app/`, FastAPI, with routers for
`studies`, `infer`, `full_grading`, `feedback`, `patients`.

## 5. API surface

`lib/api.ts` is the single place the frontend talks to the backend. Grouped:

- **worklist** `getPatients`, `createStudy`, `updateStudy`, `deleteStudy`,
  `getStudyDetail`, `uploadStudy`
- **series** `getSeries`, `setActiveSeries` (one study can hold several
  acquisitions, e.g. sagittal and axial)
- **viewing** `fullGradingSliceUrl`, mask endpoints, `saveMask`
- **inference** `runInference`, `getAnnotation`, `runFullGrading`,
  `getFullGrading`, `startFullGrading` + `getJob` (the async, polled path)
- **feedback loop** `getCorrections`, `submitCorrections`,
  `getCorrectionBatches`
- **re-training** `getRetrainReadiness`, `startBatchRetrain` + `getJob`,
  `getRetrainRuns` (the run log shown on `/admin`). A run trains on **every
  correction sent so far** by default (`scope: "all"`, deduped to the latest
  edit per grade); `scope: "batch"` trains on the launching batch alone and is
  what makes a past run reproducible. The batch id is recorded either way. The replay set of original
  discs is not in this repo: `RETRAIN_REPLAY_DIR` in `backend/.env` points at
  `rsna_preprocessed` (~8.2 GB). Unset or missing → `/admin` shows the blocked
  state and the run is refused unless asked for `without_replay`.
- **model registry** `getModelVersions`, `activateModel`, `revertModel`
- **export** `exportUrl`, `fullGradingCsvUrl`, `fullGradingJsonUrl`

`API_BASE_URL` comes from `VITE_API_URL` and defaults to
`http://localhost:8000`, which is what makes the SSH-tunnel setup work with no
CORS configuration.

## 6. Running it

### All local (no GPU)

```bash
cd ~/spine-labeling-app
./run.sh            # backend :8000 + frontend :5173
./run.sh stop
./run.sh logs
```

Segmentation on CPU takes about 10 minutes per volume. Grading is fast. For
pure UI work you rarely need either.

### Backend on a GPU box, frontend local (best for UI work)

Frontend stays on the laptop so Vite hot-reload is instant, while inference
runs on the GPU.

```bash
# laptop, keep this shell open
ssh -p <PORT> -L 8000:localhost:8000 root@<HOST>

# laptop, another shell
cd ~/spine-labeling-app && ./run.sh frontend
```

On the box: `./vast_setup.sh --skip-download`, then copy the checkpoint from
the laptop, then `./run.sh backend`. Full steps in `DEPLOY_VAST.md`.

Do **not** let `vast_setup.sh` fetch the checkpoint from Google Drive. Drive
enforces its download quota per **account**, not per file, so re-uploading a
fresh copy does not lift it; this cost a full day on 2026-08-23. `scp` the
243 MB file from the laptop instead (measured 29 MB/s, about ten seconds):

```bash
scp -P <PORT> backend/models/weights/phase2_cbam.pth \
  root@<HOST>:/workspace/spine-labeling-app/backend/models/weights/
# md5 50101203903b1aa3bcf3d6103daa650e
```

## 7. Gotchas that cost time

**Local MySQL refuses `root` without a password.** The default DSN in
`app/config.py` is MySQL. `backend/.env` now sets
`MYSQL_DSN=sqlite:///./spine.db`, which is the same shape `vast_setup.sh`
writes. The previous `.env` is kept as `.env.bak.20260909`. Symptom if it
regresses: backend exits at startup with
`(1045, "Access denied for user 'root'@'localhost'")` and `/health` never
answers, while the frontend serves fine.

**Headless Chrome renders the MRI canvas black.** Cornerstone3D needs WebGL.
For screenshots, force the software renderer:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --use-gl=angle --use-angle=swiftshader \
  --enable-unsafe-swiftshader --ignore-gpu-blocklist \
  --virtual-time-budget=30000 --window-size=1600,1000 \
  --screenshot=out.png http://localhost:5173/viewer/<STUDY_ID>
```

Without those flags the page and all metadata render correctly and only the
image is black, which reads like a data bug rather than a GPU one.

**A fresh SQLite database means an empty worklist.** To populate it for UI work
without running inference:

```bash
curl -X POST localhost:8000/studies -H 'Content-Type: application/json' \
  -d '{"id":"DEMO-001","patient_name":"Nguyen Van A","modality":"MR"}'
curl -X POST localhost:8000/studies/DEMO-001/upload \
  -F "file=@backend/data/try_me/107_t2.nii.gz"
```

Accepted uploads: `.zip` of a DICOM series, or a single `.mha` / `.nii` /
`.nii.gz`. Sample volumes live in `backend/data/{demo,try_me,spider_100}`.

## 8. Autonomy and boundaries

Running code, builds, tests and git commands in **this repo** does not need to
be confirmed first (standing instruction from the user).

Out of scope for a UI session:
- `/Users/kienha/spinet-v2` — the research repo. Its numbers, LaTeX and
  experiment scripts are not UI work.
- `backend/app/inference/*` and `backend/app/feedback/*` unless the UI change
  genuinely requires a new endpoint. Changing what the model outputs changes
  thesis claims.
- The feedback-loop semantics in section 2.

## 9. Known UI gaps worth fixing

Collected from advisor feedback, not yet built:

- **No way to configure the label set from the UI.** The grading model accepts
  a new label set through text prompts, which is a thesis contribution, but the
  app exposes a fixed 11. The advisor asked specifically how a doctor would
  configure which conditions are graded.
- **No axial support.** Series switching exists, but nothing downstream uses an
  axial series. The 10 subarticular labels in the dataset are unused.
- **No record of who activated a checkpoint, or when.** `/models` writes the
  `ACTIVE` pointer and nothing else; re-training runs are logged in
  `retrain_runs`, but the approval step that follows them is not. Adding an
  `activations` row (checkpoint, time, and whatever identity the app ever
  gains) would close the audit trail — the run log already has the shape.
- **No explanation surface.** The model's output appears without any indication
  of where in the image it came from. (Research note: saliency maps were
  evaluated and found unreliable for this task, so a heat-map overlay would be
  misleading rather than helpful. Anything built here should show measured
  evidence, not a decorative heat map.)
