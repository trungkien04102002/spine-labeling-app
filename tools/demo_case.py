"""Move one graded study between machines as a shared sample.

    # on a machine that has graded the study (any room):
    backend/.venv/bin/python tools/demo_case.py export p1-SPIDER-100 demo_case.zip

    # on a fresh install, after tools/fetch_assets.py:
    backend/.venv/bin/python tools/demo_case.py import demo_case.zip

Why: grading needs TotalSpineSeg plus SpineNet, about a minute on a GPU and
10+ minutes on a laptop CPU. A newcomer should see a finished result first,
before installing any of that. The imported study has no room (reader_id
NULL) and an id starting with SAMPLE-, so every room can copy it in from
"Try a sample case", the same way as the RSNA validation cases.

Paths are stored absolute in the DB, so the zip stores them relative to the
study directory and import rewrites them for the local DATA_DIR.

Run it from anywhere; it switches to backend/ so backend/.env is picked up.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
CALLER_CWD = Path.cwd()  # resolve CLI paths against this, not backend/
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from app.config import Settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models_db import Annotation, Patient, Series, Study  # noqa: E402

# Intermediate TotalSpineSeg outputs: large, and nothing reads them back.
SKIP_DIRS = {"seg_out"}


def _rel(path: str | None, study_dir: Path) -> str | None:
    if not path:
        return path
    try:
        return str(Path(path).resolve().relative_to(study_dir))
    except ValueError:
        sys.exit(f"{path} is outside {study_dir}; cannot package it")


def _abs(rel: str | None, study_dir: Path) -> str | None:
    return str(study_dir / rel) if rel else rel


def export(study_id: str, out: Path, name: str, patient: str | None) -> None:
    data_root = Path(Settings().data_dir).resolve()
    study_dir = data_root / study_id
    db = SessionLocal()
    study = db.get(Study, study_id)
    if study is None:
        sys.exit(f"No study {study_id}")
    ai = (
        db.query(Annotation)
        .filter_by(study_id=study_id, kind="ai")
        .order_by(Annotation.version, Annotation.id)
        .all()
    )
    if not ai:
        sys.exit(f"{study_id} has no AI result; grade it first")
    series = db.query(Series).filter_by(study_id=study_id).order_by(Series.id).all()
    analyzed = [s.id for s in series].index(study.analyzed_series_id) if (
        study.analyzed_series_id in [s.id for s in series]
    ) else None

    manifest = {
        "id": name,
        "patient_name": patient or db.get(Patient, study.patient_id).name,
        "modality": study.modality,
        "volume_path": _rel(study.volume_path, study_dir),
        "display_path": _rel(study.display_path, study_dir),
        "analyzed_series_index": analyzed,
        "series": [
            {
                "series_uid": s.series_uid,
                "description": s.description,
                "orientation": s.orientation,
                "volume_path": _rel(s.volume_path, study_dir),
                "display_path": _rel(s.display_path, study_dir),
                "num_slices": s.num_slices,
            }
            for s in series
        ],
        "annotations": [
            {
                "version": a.version,
                "kind": a.kind,
                "payload_json": a.payload_json,
                "mask_path": _rel(a.mask_path, study_dir),
            }
            for a in ai
        ],
    }
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=1))
        for f in sorted(study_dir.rglob("*")):
            rel = f.relative_to(study_dir)
            if f.is_file() and rel.parts[0] not in SKIP_DIRS:
                z.write(f, f"files/{rel}")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB) as sample {name}")


def import_(zip_path: Path) -> None:
    init_db()
    data_root = Path(Settings().data_dir).resolve()
    with zipfile.ZipFile(zip_path) as z:
        manifest = json.loads(z.read("manifest.json"))
        sid = manifest["id"]
        study_dir = data_root / sid
        db = SessionLocal()
        if db.get(Study, sid) is not None:
            print(f"{sid} is already in the database; nothing to do")
            return
        with tempfile.TemporaryDirectory() as tmp:
            z.extractall(tmp)
            study_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(Path(tmp) / "files", study_dir, dirs_exist_ok=True)

    patient = Patient(name=manifest["patient_name"], reader_id=None)
    db.add(patient)
    db.flush()
    study = Study(
        id=sid,
        patient_id=patient.id,
        reader_id=None,
        modality=manifest["modality"],
        volume_path=_abs(manifest["volume_path"], study_dir),
        display_path=_abs(manifest["display_path"], study_dir),
    )
    db.add(study)
    db.flush()
    rows = []
    for s in manifest["series"]:
        row = Series(
            study_id=sid,
            series_uid=s["series_uid"],
            description=s["description"],
            orientation=s["orientation"],
            volume_path=_abs(s["volume_path"], study_dir),
            display_path=_abs(s["display_path"], study_dir),
            num_slices=s["num_slices"],
        )
        db.add(row)
        db.flush()
        rows.append(row)
    if manifest["analyzed_series_index"] is not None:
        study.analyzed_series_id = rows[manifest["analyzed_series_index"]].id
    for a in manifest["annotations"]:
        db.add(
            Annotation(
                study_id=sid,
                version=a["version"],
                kind=a["kind"],
                payload_json=a["payload_json"],
                mask_path=_abs(a["mask_path"], study_dir),
            )
        )
    db.commit()
    print(f"imported sample {sid} into {study_dir}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("study_id")
    e.add_argument("out", type=Path)
    e.add_argument("--name", default="SAMPLE-SPIDER-100", help="id on import")
    e.add_argument("--patient", default="SPIDER 100", help="patient name shown")
    i = sub.add_parser("import")
    i.add_argument("zip", type=Path)
    a = p.parse_args()
    if a.cmd == "export":
        export(a.study_id, CALLER_CWD / a.out, a.name, a.patient)
    else:
        import_(CALLER_CWD / a.zip)


if __name__ == "__main__":
    main()
