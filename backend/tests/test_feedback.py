"""Tests for the doctor-feedback fine-tune dataset builder.

Uses synthetic `CorrectionLog` rows in a temp in-memory SQLite DB (same
pattern as `test_infer.py`) and a stubbed crop function, so no real
volumes/masks/models are needed -- only the label-mapping + CSV/npy assembly
logic in `app.feedback.build_dataset` is exercised.
"""

import csv
import datetime

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.feedback.build_dataset import build_finetune_dataset
from app.models_db import Annotation, CorrectionLog, Patient, Study


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _seed_study_with_annotation(
    db, study_id="s1", volume_path="/fake/data/s1/vol.mha", mask_path="/fake/data/s1/mask.nii.gz"
):
    patient = Patient(name="Demo")
    db.add(patient)
    db.commit()
    db.refresh(patient)
    db.add(Study(id=study_id, patient_id=patient.id, volume_path=volume_path))
    db.add(
        Annotation(
            study_id=study_id,
            version=0,
            kind="ai",
            payload_json={"grading": []},
            mask_path=mask_path,
        )
    )
    db.commit()


def _stub_crop_fn(calls=None):
    """A crop_fn stub returning a deterministic array; records call args."""

    def _fn(volume_path, mask_path, level):
        if calls is not None:
            calls.append((volume_path, mask_path, level))
        return np.full((9, 112, 224), 0.5, dtype=np.float32)

    return _fn


def _read_metadata(metadata_csv):
    with open(metadata_csv, newline="") as f:
        return list(csv.DictReader(f))


def test_build_dataset_writes_crops_and_metadata_from_corrections(db, tmp_path):
    _seed_study_with_annotation(db)
    db.add(
        CorrectionLog(
            study_id="s1", field="L4-L5/canal_stenosis", old="Normal/Mild", new="Severe"
        )
    )
    db.add(
        CorrectionLog(
            study_id="s1", field="L4-L5/left_foraminal", old="Normal/Mild", new="Moderate"
        )
    )
    db.commit()

    calls = []
    result = build_finetune_dataset(
        db, str(tmp_path / "out"), crop_fn=_stub_crop_fn(calls)
    )

    assert result.num_rows == 1
    assert result.num_corrections_used == 2
    assert result.skipped == []
    assert calls == [("/fake/data/s1/vol.mha", "/fake/data/s1/mask.nii.gz", "L4-L5")]

    rows = _read_metadata(result.metadata_csv)
    assert len(rows) == 1
    row = rows[0]
    assert row["study_id"] == "s1"
    assert row["filepath"] == "s1/l4_l5.npy"
    assert row["spinal_canal"] == "2"  # Severe
    assert row["left_foraminal"] == "1"  # Moderate
    assert row["right_foraminal"] == "-1"  # not corrected -> ignore_index

    crop_path = tmp_path / "out" / "volumes" / "s1" / "l4_l5.npy"
    assert crop_path.is_file()
    crop = np.load(crop_path)
    assert crop.shape == (9, 112, 224)


def test_keeps_only_latest_correction_for_same_field(db, tmp_path):
    _seed_study_with_annotation(db)
    db.add(
        CorrectionLog(
            study_id="s1",
            field="L4-L5/canal_stenosis",
            old="Normal/Mild",
            new="Moderate",
            at=datetime.datetime(2024, 1, 1),
        )
    )
    db.add(
        CorrectionLog(
            study_id="s1",
            field="L4-L5/canal_stenosis",
            old="Moderate",
            new="Severe",
            at=datetime.datetime(2024, 1, 2),
        )
    )
    db.commit()

    result = build_finetune_dataset(db, str(tmp_path / "out"), crop_fn=_stub_crop_fn())

    assert result.num_corrections_used == 1  # deduped to the latest edit
    rows = _read_metadata(result.metadata_csv)
    assert len(rows) == 1
    assert rows[0]["spinal_canal"] == "2"  # Severe (the later correction), not Moderate


def test_missing_volume_is_skipped(db, tmp_path):
    patient = Patient(name="Demo")
    db.add(patient)
    db.commit()
    db.refresh(patient)
    db.add(Study(id="no_vol", patient_id=patient.id, volume_path=None))
    db.add(
        Annotation(
            study_id="no_vol",
            version=0,
            kind="ai",
            payload_json={"grading": []},
            mask_path="/fake/mask.nii.gz",
        )
    )
    db.add(CorrectionLog(study_id="no_vol", field="L4-L5/canal_stenosis", new="Severe"))
    db.commit()

    result = build_finetune_dataset(db, str(tmp_path / "out"), crop_fn=_stub_crop_fn())

    assert result.num_rows == 0
    assert any("missing volume or mask" in s for s in result.skipped)


def test_missing_mask_is_skipped(db, tmp_path):
    patient = Patient(name="Demo")
    db.add(patient)
    db.commit()
    db.refresh(patient)
    # Study has a volume but no annotation at all yet -> no mask on record.
    db.add(Study(id="no_mask", patient_id=patient.id, volume_path="/fake/v.mha"))
    db.add(CorrectionLog(study_id="no_mask", field="L4-L5/canal_stenosis", new="Severe"))
    db.commit()

    result = build_finetune_dataset(db, str(tmp_path / "out"), crop_fn=_stub_crop_fn())

    assert result.num_rows == 0
    assert any("missing volume or mask" in s for s in result.skipped)


def test_disc_not_found_in_mask_is_skipped(db, tmp_path):
    _seed_study_with_annotation(db)
    db.add(CorrectionLog(study_id="s1", field="L4-L5/canal_stenosis", new="Severe"))
    db.commit()

    result = build_finetune_dataset(
        db, str(tmp_path / "out"), crop_fn=lambda vp, mp, level: None
    )

    assert result.num_rows == 0
    assert any("disc not found in mask" in s for s in result.skipped)


def test_unknown_severity_is_skipped_but_does_not_crash(db, tmp_path):
    _seed_study_with_annotation(db)
    db.add(
        CorrectionLog(study_id="s1", field="L4-L5/canal_stenosis", new="Not A Real Severity")
    )
    db.commit()

    result = build_finetune_dataset(db, str(tmp_path / "out"), crop_fn=_stub_crop_fn())

    assert result.num_rows == 0  # the only condition on this disc was unrecognized
    assert any("unknown condition or severity" in s for s in result.skipped)
