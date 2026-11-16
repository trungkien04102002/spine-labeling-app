# AGENTS.md

Briefing for an AI agent (or a new developer) working in this repo. Read
[README.md](README.md) for what the app is and how to run it; this file is
what you need on top of that to change it safely.

## Start here

```bash
tools/check.sh            # must pass before and after your change (~2 min)
tools/check.sh --gpu      # if the change touches upload, inference or results
./run.sh / ./run.sh stop  # backend :8000 + frontend :5173; logs: ./run.sh logs
```

The backend does **not** hot-reload under `run.sh` (use `RELOAD=1 ./run.sh`
for that). After a backend change, restart before testing in the browser.

Before saying a UI change works, look at it: open the page (Playwright is a
frontend dev dependency; run `cd frontend && npx playwright install chromium`
once; `tools/diagnose_viewer.mjs` is a working example) and check the image is
actually drawn. A 200 from the API proves nothing about
the viewer.

## Map

| Where | What |
|---|---|
| `backend/app/routers/studies.py` | create study, upload (DICOM zip / NIfTI / MHA), series, mask, export |
| `backend/app/inference/volume_io.py` | every upload format -> one NIfTI per series; picks the sagittal T2 |
| `backend/app/routers/full_grading.py` | grading as a background job: `POST …/grade_full/start`, poll `GET /jobs/{id}` |
| `backend/app/inference/full_grading.py` | runs TotalSpineSeg -> SpineNet -> model A and merges (`merge_gradings`) |
| `backend/app/inference/grading.py` | model A; loads the checkpoint named in `backend/models/weights/ACTIVE` (always built with CBAM, so a `--no-cbam` checkpoint will not load) |
| `backend/app/feedback/` | correction batches, frozen hold-out, re-training, model registry |
| `backend/app/survey_questions.py` | survey items; ids are frozen (a test enforces it) |
| `frontend/src/pages/Viewer.tsx` | the main screen; owns nearly all its state |
| `frontend/src/components/Viewer/CornerstoneViewport.tsx` | the WebGL image + mask |
| `frontend/src/lib/api.ts` | every backend call |
| `frontend/src/lib/strings.vi.ts` | all Vietnamese UI text, keyed by the English string |

## Rules that are easy to break

1. **The 11 findings come from two models.** `canal_stenosis`,
   `left_foraminal`, `right_foraminal` come from model A (this thesis); the
   other 8 from upstream SpineNet. SpineNet also outputs its own canal and
   foraminal grades; `merge_gradings` drops those on purpose. Do not show both.
2. **Corrections are never applied to the model immediately.** They are
   queued, batched, re-trained offline into a candidate, and a person
   activates it. This is a design claim of the thesis (a correction on
   patient A must not silently change patient B's result). Keep the UI from
   suggesting otherwise.
3. **Label `-1` means "missing"** in training data and must survive any
   change to class weights, losses or augmentation.
4. **Paths in the DB are absolute.** Copying `spine.db` to another machine or
   directory makes every study open blank while the worklist looks fine.
   Rewrite the prefix, or use `tools/demo_case.py` for single studies.
5. **Study ids are room-prefixed.** A clinician's "ca1" in room 6 is
   `p6-ca1` in the DB and on disk (`backend/data/p6-ca1/`). Unowned studies
   (no prefix, `reader_id` NULL) are shared samples matching `SAMPLE_STUDIES`.
6. **Upload and delete are refused (409) while a study is being graded**, so
   a new file cannot replace the volume a running job reads.
7. **Every user-facing string goes through `t("English text")`** with the
   Vietnamese in `strings.vi.ts`. Clinician wording is plain and uses the
   Vietnamese radiology terms already in that file (e.g. "mâm sụn" for
   endplate, "thay đổi Modic" for marrow change); reuse them.
8. **Do not commit** weights, `backend/data/`, `*.db`, `backend/.env`, or any
   patient data. RSNA data may not be redistributed (Kaggle rules).

## Bugs already met (symptom -> cause)

| Symptom | Cause / where it was fixed |
|---|---|
| Image black on every study, rest of the page fine | built with `VITE_API_URL=""` before relative URLs were handled; `api.ts` now resolves empty to `window.location.origin` |
| Image black on ~half of all openings | a new WebGL rendering engine per viewer mount; now one shared engine |
| Sagittal black or a thin smear (oblique Siemens scans) | nifti-volume-loader 5.2.1 slice spacing bug; `fixNiftiSlicePositions` |
| STIR almost black | min-max window with saturated pixels; `robustWindow` (p1-p99.5) |
| "Offset is outside the bounds of the DataView" after grading | mask written twice while the browser read it; now written once, atomically |
| White page right after grading | legend read a colour while the segmentation was being torn down |
| Grading 2-3x slower on a rented box, GPU idle | container reports 26 CPUs but cgroup allows ~6; `app/cpu_threads.py` sets thread counts from the cgroup quota (keep it the first import in `main.py`) |
| torch sees no GPU, everything silently 10x slower | PyPI torch built for a newer CUDA than the driver; `vast_setup.sh` refetches a matching wheel |
| "save path …/detect-vfr could not be found" | SpineNet weights missing: `python3 tools/fetch_assets.py models` |
| Backend exits at start with MySQL "Access denied" | an old `.env` with a MySQL DSN; the default is now SQLite |
| Users see the old UI after an update | cached JavaScript in an open tab; hard refresh. `index.html` is served `no-cache` |

Still open:
- The mask is matched to a series only by voxel count, so on a study whose T1
  and T2 have the same dimensions the T2 mask is drawn over the T1 too.
- A single `.nii`/`.mha` upload has no series description, so nothing warns
  when it is not a sagittal T2.
- Enhanced multi-frame DICOM (one file, many slices) is untested.

## Testing notes

- `cd backend && .venv/bin/python -m pytest -q -k "not end_to_end"`: in-memory
  SQLite, no GPU, no weights. Tests needing outside data skip themselves; the
  research repo's data is found through `SPINET_V2_DIR` (default
  `../spinet-v2`), TotalSpineSeg's own sample through `SEG_TEST_VOLUME` with
  `RUN_SEG_TEST=1`.
- Frontend has no unit tests: `npm run lint` (oxlint) and `npm run build`
  (`tsc -b` + Vite) are the gate.
- `tools/smoke_grade.py` is the end-to-end test: real upload, real grading.
- Headless Chrome draws the MRI canvas black unless it uses software WebGL:
  `--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader
  --ignore-gpu-blocklist` (already set in `diagnose_viewer.mjs`).

## Known gaps (asked for by the advisor, not built)

- The label set is fixed at 11 in the UI, although the research model can
  take new labels through text prompts.
- Axial series are displayed but never graded (the 10 subarticular labels of
  RSNA are unused).
- No audit row for who activated a checkpoint and when.
- No explanation of where in the image a grade came from. Saliency maps were
  evaluated in the research repo and did no better than a fixed centre guess
  on these centred crops, so a heat-map overlay would mislead.
