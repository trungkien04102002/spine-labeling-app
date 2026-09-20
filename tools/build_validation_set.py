"""Zip the chosen RSNA studies, push them through the app, and grade them.

Reads the manifest from `tools/pick_validation_cases.py`, and for each case:
zips the study's DICOM series, creates the study over the API, uploads it, then
runs the full 11-label grading and saves the raw result.

Each step is skippable and resumable, because grading is the slow part (~1 min
per study on a GPU box, ~10 on CPU) and re-zipping or re-uploading to redo a
failed grade would waste it.

    python3 tools/build_validation_set.py --api http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import time
import zipfile
from pathlib import Path

import requests

RSNA_IMAGES = Path(
    "/Users/kienha/spinet-v2/"
    "rsna-2024-lumbar-spine-degenerative-classification/train_images"
)
REPO = Path(__file__).resolve().parents[1]


def study_prefix(study_id: str) -> str:
    """Study id used inside the app.

    Prefixed so these never collide with -- or get mistaken for -- a real
    uploaded case in the worklist.
    """
    return f"VAL-{study_id}"


def zip_study(study_id: str, out_dir: Path) -> Path:
    """Pack every series of one study into a single .zip.

    All series go in, not just the sagittal T2 the model reads: the app regroups
    files by SeriesInstanceUID on upload, and having T1/axial present is what a
    real study looks like in the viewer.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{study_id}.zip"
    if zip_path.exists():
        print(f"    zip exists ({zip_path.stat().st_size / 1e6:.1f} MB)")
        return zip_path
    src = RSNA_IMAGES / study_id
    files = sorted(src.rglob("*.dcm"))
    if not files:
        raise SystemExit(f"no DICOM files under {src}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            # Keep <series_id>/<file>.dcm so the archive stays readable by hand.
            zf.write(path, arcname=str(path.relative_to(src)))
    print(f"    zipped {len(files)} files -> {zip_path.stat().st_size / 1e6:.1f} MB")
    return zip_path


def ensure_study(api: str, study_id: str, patient_name: str) -> None:
    app_id = study_prefix(study_id)
    resp = requests.get(f"{api}/studies/{app_id}", timeout=30)
    if resp.status_code == 200:
        print("    study already exists")
        return
    resp = requests.post(
        f"{api}/studies",
        json={"id": app_id, "patient_name": patient_name, "modality": "MR"},
        timeout=30,
    )
    resp.raise_for_status()
    print("    study created")


def upload(api: str, study_id: str, zip_path: Path) -> None:
    app_id = study_prefix(study_id)
    detail = requests.get(f"{api}/studies/{app_id}", timeout=30)
    if detail.status_code == 200 and detail.json().get("has_volume"):
        print("    volume already uploaded")
        return
    with zip_path.open("rb") as fh:
        resp = requests.post(
            f"{api}/studies/{app_id}/upload",
            files={"file": (zip_path.name, fh, "application/zip")},
            timeout=1800,
        )
    resp.raise_for_status()
    print("    uploaded")


def grade(api: str, study_id: str, out_dir: Path, force: bool) -> dict:
    """Run the async grading job and poll it to completion."""
    app_id = study_prefix(study_id)
    out_path = out_dir / f"{study_id}.grading.json"
    if out_path.exists() and not force:
        print("    grading result cached")
        return json.loads(out_path.read_text())

    resp = requests.post(f"{api}/studies/{app_id}/grade_full/start", timeout=60)
    resp.raise_for_status()
    job_id = resp.json()["id"]

    last_stage = ""
    while True:
        time.sleep(5)
        job = requests.get(f"{api}/jobs/{job_id}", timeout=30).json()
        if job["stage"] != last_stage:
            last_stage = job["stage"]
            print(f"    [{job['percent']:>3}%] {job['stage']}")
        if job["status"] == "done":
            break
        if job["status"] == "error":
            raise SystemExit(f"grading failed for {study_id}: {job['error']}")

    result = requests.get(f"{api}/studies/{app_id}/grade_full", timeout=60).json()
    out_path.write_text(json.dumps(result, indent=2))
    print(f"    graded in {job['elapsed_seconds']:.0f}s -> {out_path.name}")
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--manifest", default="tools/validation_cases.json")
    ap.add_argument("--out-dir", default="data/validation_set")
    ap.add_argument("--only", help="run a single study_id")
    ap.add_argument("--skip-grading", action="store_true")
    ap.add_argument("--force-grading", action="store_true")
    args = ap.parse_args()

    health = requests.get(f"{args.api}/health", timeout=15)
    health.raise_for_status()
    print(f"backend at {args.api}: {health.json()}\n")

    cases = json.loads(Path(args.manifest).read_text())["cases"]
    if args.only:
        cases = [c for c in cases if c["study_id"] == args.only]
    out_dir = REPO / args.out_dir

    for i, case in enumerate(cases, 1):
        study_id = case["study_id"]
        kind = (
            "severe canal" if case["canal_severe"]
            else "severe foraminal" if case["foraminal_severe"]
            else "normal/mild"
        )
        print(f"[{i}/{len(cases)}] {study_id}  ({kind})")
        zip_path = zip_study(study_id, out_dir / "zips")
        ensure_study(args.api, study_id, f"RSNA {study_id}")
        upload(args.api, study_id, zip_path)
        if not args.skip_grading:
            grade(args.api, study_id, out_dir / "results", args.force_grading)
        print()


if __name__ == "__main__":
    main()
