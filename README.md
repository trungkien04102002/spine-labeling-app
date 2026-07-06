# spine-labeling-app

A local web tool for doctors to open a lumbar-spine MRI, review AI-generated overlays (anatomy segmentation + abnormality grading), correct them, and export the results. MySQL stores metadata/annotations only; MRI volumes and masks live on the filesystem.

Backend: `cd backend && uvicorn app.main:app --reload`

## Segmentation (TotalSpineSeg)

Anatomy segmentation uses [TotalSpineSeg](https://github.com/neuropoly/totalspineseg).
It pins `numpy<2` and pulls in nnU-Net/torchio, which conflict with this
backend's torch/numpy, so it is **not** installed here — it runs as an external
CLI (see `app/inference/segmentation.py`). Install it in its own environment:

```bash
python -m venv totalspineseg-venv && source totalspineseg-venv/bin/activate
pip install totalspineseg
totalspineseg_init            # downloads the pretrained nnU-Net weights (~460 MB)
```

Then point the backend at that CLI (env or `.env`):

```bash
TOTALSPINESEG_BIN=/abs/path/to/totalspineseg-venv/bin/totalspineseg
SEG_DEVICE=cpu                # or "cuda"
```

The heavy end-to-end segmentation test is opt-in:
`RUN_SEG_TEST=1 pytest backend/tests/test_seg.py`.
