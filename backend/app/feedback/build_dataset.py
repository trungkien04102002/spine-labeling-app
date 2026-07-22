"""Build a head-only fine-tune dataset from doctor corrections.

This is the deliberately-simple "future work" feedback loop the advisor asked
for: give a doctor ~10-20 studies, log their corrections, and turn those
corrections into a small training set the deployed grading model can be
lightly re-tuned on (see ``retrain_head.py``).

Pipeline:
    ``correction_log`` (+ latest ``annotations`` row per study, for the mask)
    -> regenerate the per-disc ``(9, 112, 224)`` crop via
       :func:`app.inference.crops.extract_disc_crops`
    -> map the corrected severity string back to a class index (the inverse of
       :data:`app.inference.grading._SEVERITY_BY_CLASS`)
    -> write one ``.npy`` crop per (study, level) + one RSNA-metadata-style CSV
       row (``spinal_canal`` / ``left_foraminal`` / ``right_foraminal`` columns,
       ``-1`` = "no correction for this head on this disc", matching the
       ``ignore_index=-1`` convention `spinenet-v2` trains with).
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import SimpleITK as sitk
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.inference.crops import extract_disc_crops
from app.inference.grading import _HEAD_TO_CONDITION, _SEVERITY_BY_CLASS
from app.inference.volume_io import _orient_slices_last, _read_image
from app.models_db import Annotation, CorrectionLog, Study

logger = logging.getLogger("uvicorn.error")

# GradingItem.condition -> RSNA head/column name (inverse of grading.py's map).
_CONDITION_TO_HEAD = {v: k for k, v in _HEAD_TO_CONDITION.items()}
# Severity string -> class index (inverse of grading.py's map).
_CLASS_BY_SEVERITY = {v: k for k, v in _SEVERITY_BY_CLASS.items()}

_HEADS = ("spinal_canal", "left_foraminal", "right_foraminal")
_METADATA_COLUMNS = ("study_id", "filepath", *_HEADS)

# A crop regenerator: (volume_path, mask_path, level) -> (9, 112, 224) array,
# or None if the level isn't present in the mask. Overridable (e.g. in tests)
# so `build_finetune_dataset` doesn't need real volumes/masks on disk.
CropFn = Callable[[str, str, str], "np.ndarray | None"]


def _level_slug(level: str) -> str:
    """"L4-L5" -> "l4_l5" (filesystem-safe filename stem)."""
    return level.lower().replace("-", "_")


def default_crop_fn(volume_path: str, mask_path: str, level: str) -> np.ndarray | None:
    """Regenerate one disc's crop the same way `inference.local` does live."""
    vol_arr = sitk.GetArrayFromImage(_orient_slices_last(_read_image(volume_path)))
    mask_arr = sitk.GetArrayFromImage(_orient_slices_last(_read_image(mask_path)))
    data = extract_disc_crops(vol_arr, mask_arr).get(level)
    return data["crop"] if data else None  # type: ignore[return-value]


def _latest_corrections(db: Session) -> list[CorrectionLog]:
    """One `CorrectionLog` row per (study_id, field): the most recent by `at`.

    Handles "multiple corrections on the same disc" -- a doctor can correct the
    same field more than once; only the latest edit should feed training.
    """
    rows = (
        db.query(CorrectionLog)
        .order_by(CorrectionLog.at, CorrectionLog.id)
        .all()
    )
    latest: dict[tuple[str, str], CorrectionLog] = {}
    for row in rows:  # later rows in `at`/id order overwrite -> latest wins
        latest[(row.study_id, row.field)] = row
    return list(latest.values())


def _latest_mask_path(db: Session, study_id: str) -> str | None:
    """The most recent annotation's mask path (mask is carried forward across
    correction versions -- see `routers/infer.py::save_annotation`)."""
    ann = (
        db.query(Annotation)
        .filter_by(study_id=study_id)
        .order_by(desc(Annotation.version), desc(Annotation.id))
        .first()
    )
    return ann.mask_path if ann else None


@dataclass
class BuildResult:
    out_dir: Path
    metadata_csv: Path
    num_rows: int
    num_corrections_used: int
    skipped: list[str] = field(default_factory=list)


def build_finetune_dataset(
    db: Session,
    out_dir: str,
    crop_fn: CropFn | None = None,
) -> BuildResult:
    """Turn logged doctor corrections into a small fine-tune dataset on disk.

    Args:
        db: an active SQLAlchemy session (queries `CorrectionLog`, `Study`,
            `Annotation`).
        out_dir: directory to write `volumes/<study_id>/<level>.npy` crops and
            `train_metadata.csv` into (created if missing).
        crop_fn: how to regenerate a disc crop; defaults to
            :func:`default_crop_fn` (real volume/mask -> `extract_disc_crops`).
            Tests can inject a stub here instead of writing real volumes/masks.

    Returns:
        A `BuildResult` summarizing what was written and what was skipped
        (missing volume/mask, disc not found in the mask, unknown
        condition/severity string).
    """
    crop_fn = crop_fn or default_crop_fn
    out_path = Path(out_dir)
    volumes_dir = out_path / "volumes"
    volumes_dir.mkdir(parents=True, exist_ok=True)

    corrections = _latest_corrections(db)

    # Group per-condition corrections onto their shared disc: the grading
    # model outputs all three heads per crop, so one dataset row per
    # (study_id, level), with -1 for heads the doctor didn't touch.
    per_disc: dict[tuple[str, str], dict[str, str]] = {}
    skipped: list[str] = []
    for row in corrections:
        try:
            level, condition = row.field.split("/", 1)
        except ValueError:
            skipped.append(f"{row.study_id}:{row.field} (unparseable field)")
            continue
        per_disc.setdefault((row.study_id, level), {})[condition] = row.new

    metadata_rows: list[dict[str, object]] = []
    mask_volume_cache: dict[str, tuple[str | None, str | None]] = {}

    for (study_id, level), cond_sevs in sorted(per_disc.items()):
        if study_id not in mask_volume_cache:
            study = db.get(Study, study_id)
            volume_path = study.volume_path if study else None
            mask_path = _latest_mask_path(db, study_id)
            mask_volume_cache[study_id] = (volume_path, mask_path)
        volume_path, mask_path = mask_volume_cache[study_id]

        if not volume_path or not mask_path:
            skipped.append(f"{study_id}/{level} (missing volume or mask)")
            continue

        try:
            crop = crop_fn(volume_path, mask_path, level)
        except (FileNotFoundError, OSError, RuntimeError) as exc:
            skipped.append(f"{study_id}/{level} (crop extraction failed: {exc})")
            continue

        if crop is None:
            skipped.append(f"{study_id}/{level} (disc not found in mask)")
            continue

        row_labels: dict[str, int] = {h: -1 for h in _HEADS}
        for condition, severity in cond_sevs.items():
            head = _CONDITION_TO_HEAD.get(condition)
            class_idx = _CLASS_BY_SEVERITY.get(severity)
            if head is None or class_idx is None:
                skipped.append(
                    f"{study_id}/{level}/{condition} (unknown condition or "
                    f"severity: {severity!r})"
                )
                continue
            row_labels[head] = class_idx

        if all(v == -1 for v in row_labels.values()):
            # Every condition on this disc had an unrecognized severity/label.
            continue

        filename = f"{_level_slug(level)}.npy"
        study_dir = volumes_dir / study_id
        study_dir.mkdir(parents=True, exist_ok=True)
        np.save(study_dir / filename, np.asarray(crop, dtype=np.float32))

        metadata_rows.append(
            {
                "study_id": study_id,
                "filepath": f"{study_id}/{filename}",
                **row_labels,
            }
        )

    metadata_csv = out_path / "train_metadata.csv"
    with open(metadata_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(_METADATA_COLUMNS))
        writer.writeheader()
        writer.writerows(metadata_rows)

    if skipped:
        logger.info("build_finetune_dataset: skipped %d disc(s): %s", len(skipped), skipped)

    return BuildResult(
        out_dir=out_path,
        metadata_csv=metadata_csv,
        num_rows=len(metadata_rows),
        num_corrections_used=len(corrections),
        skipped=skipped,
    )


def _cli() -> None:
    """`python -m app.feedback.build_dataset --out-dir <dir>` entry point."""
    import argparse

    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, help="Output dataset directory")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = build_finetune_dataset(db, args.out_dir)
    finally:
        db.close()

    print(f"Wrote {result.num_rows} row(s) to {result.metadata_csv}")
    print(f"Used {result.num_corrections_used} correction(s); skipped {len(result.skipped)}")
    for reason in result.skipped:
        print(f"  skipped: {reason}")


if __name__ == "__main__":
    _cli()
