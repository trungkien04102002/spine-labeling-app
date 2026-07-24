# Handoff — spine-labeling-app session, 2026-07-24

Resume point for the Claude Code **terminal** session (main-thesis-session).
Everything below is committed + pushed. App tested and left running.

## What was done this session

### 1. Fixed "Full grading" bug — app `dea54b1`
- `TOTALSPINESEG_BIN` defaulted to a bare `totalspineseg` not on the backend
  PATH → `FileNotFoundError`. Now resolved via `shutil.which`/`isfile` with a
  clear error; configured per-machine in `backend/.env` (gitignored):
  `TOTALSPINESEG_BIN=/Users/kienha/totalspineseg/venv/bin/totalspineseg`, `SEG_DEVICE=cpu`.
- `pixel_spacing` was a `(sy,sx)` tuple; upstream `detect_vb` needs a scalar →
  `float(np.mean([sy,sx]))`. Verified E2E (479s CPU on a SPIDER study).

### 2. Unified grading UI — app `cfdc7a2`
- Two overlapping grade panels + two run buttons → **one `✨ Run AI` button + one
  editable 11-label "Abnormality grades" panel** (Pfirrmann, narrowing, canal,
  foraminal L/R, spondy, endplate ×2, marrow ×2, herniation).
- `/grade_full` now persists the segmentation mask (via `to_web_mask`, like
  `/infer`) and saves a v0 AI annotation, so the existing
  edit → `/annotations` → `correction_log` pipeline works on all 11 labels.
  `FullGradingResult` gained a `segmentation` field.
- Panel = editable (dropdown + Undo/Redo + Save corrections) + Export + CSV/JSON
  + labelled slice image. Added **"About this tool"** (what each grade means,
  CBAM vs SpineNet source, research-only disclaimer — Oxford-demo style) and a
  **"Doctor feedback"** section (corrections feed periodic retraining).
- Verified E2E: `POST /grade_full` → `getAnnotation` returns 11 conditions +
  segmentation; UI renders the 11-column editable table (screenshot-checked).

### 3. Zipped-DICOM upload — app `3c88178`
- Web upload only took a single volume file; a DICOM series (a directory) could
  not be uploaded. Added `extract_dicom_zip()` (volume_io.py): unpacks a `.zip`,
  flattens entries, guards zip-slip, skips `__MACOSX`/dotfiles, verifies
  SimpleITK finds a series, points `volume_path` at the extracted dir.
- Unsupported types + non-DICOM/corrupt zips → 400 with a clear message.
  Frontend file picker now accepts `.zip`.
- Verified E2E through the running server: create study → upload
  `sample_volumes/sample_dicom.zip` → HTTP 200, dims [608,608,28], 28 slices,
  display.nii.gz served.

### Supported input formats (after this session)
| Format | Web upload | Notes |
|---|---|---|
| `.zip` of a DICOM series | ✅ new | flatten + verify; Oxford-demo style |
| `.mha` (SPIDER) | ✅ | |
| `.nii` / `.nii.gz` | ✅ | |
| DICOM series as a directory | ✅ | only when `volume_path` is already a dir (import), not via upload |
| single `.dcm` | ⚠️ | reads 1 slice only, not a real volume |

### Sample files added — `sample_volumes/` (gitignored, local only)
All input types now present for testing:
`100_t2.mha`, `105_t2.mha`, `107_t2.mha`, `sample_ct.nii`, `sample_ct.nii.gz`,
`sample_dicom_series/` (28 `.dcm`), `sample_dicom.zip` (28-slice DICOM zip).

## State / verification
- Backend suite: **66 passed, 1 skipped**. Frontend lint + build clean.
- Both repos pushed: app `main`@`3c88178`; spinet-v2 `biomedclip-integration`@`6d47d46`
  (tracker + advisor Q&A docs).
- App is currently **running** (BE :8000, FE :5173). Stop with `./run.sh stop`.

## How to run
```bash
cd ~/spine-labeling-app && ./run.sh both     # BE :8000 + FE :5173
# open http://localhost:5173  ·  logs: ./run.sh logs  ·  stop: ./run.sh stop
```
Needs `backend/.env` (see item 1). ⚠️ "Run AI" is ~8–15 min on CPU (nnU-Net).

## Not done / next (see `~/spinet-v2/docs/LVTN_phase3/00_TRACKER.md`)
- GPU batch: train #1 T1-foraminal, #2/#3 multi-view, SOTA `run_all.sh` (seed 42).
- Then: lock F1 numbers → write thesis method/experiments chapters.
- Software polish: dropdown options per-condition, async job/progress for "Run AI",
  demo video. Feedback-loop retrain stays FUTURE WORK (write-up only).
- Axial: stretch/future — unique value is subarticular (not in current labels);
  see `00_TRACKER.md` §3 + `MULTIVIEW_RESEARCH.md`.
