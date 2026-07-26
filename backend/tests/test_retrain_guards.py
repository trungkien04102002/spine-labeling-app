"""Tests for the three safety guards in `app.feedback.retrain_head`.

Each guard covers a failure that is silent in the output unless tested for:
BatchNorm statistics drifting on a handful of samples, forgetting caused by
training on corrections alone, and a keep/discard gate that cannot see a
collapse of the rare `Severe` class. Rationale:
`spinet-v2/docs/LVTN_phase3/FEEDBACK_LOOP_METHODS.md`.
"""

import csv

import numpy as np
import pytest
import torch
import torch.nn as nn

from app.feedback.retrain_head import (
    _f1_per_class,
    _freeze_batchnorm,
    _nanmean,
    build_train_dataset,
)

_HEADS = ("spinal_canal", "left_foraminal", "right_foraminal")


def _write_dataset(root, n_rows: int):
    """Minimal `build_finetune_dataset()`-shaped directory."""
    volumes = root / "volumes"
    volumes.mkdir(parents=True)
    rows = []
    for i in range(n_rows):
        filename = f"disc_{i}.npy"
        np.save(volumes / filename, np.zeros((9, 112, 224), dtype=np.float32))
        rows.append({"filepath": filename, **{h: 0 for h in _HEADS}})

    with open(root / "train_metadata.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["filepath", *_HEADS])
        writer.writeheader()
        writer.writerows(rows)
    return root


# --- Guard 1: BatchNorm running statistics stay put ------------------------


def test_freeze_batchnorm_stops_running_stats_from_moving():
    model = nn.Sequential(nn.Conv3d(1, 4, 3, padding=1), nn.BatchNorm3d(4))
    # Give the BN a non-default history so a drift would be obvious.
    model.train()
    model(torch.randn(8, 1, 4, 8, 8))
    baseline_mean = model[1].running_mean.clone()
    baseline_var = model[1].running_var.clone()

    model.train()
    frozen = _freeze_batchnorm(model)
    # Wildly off-distribution input: unfrozen BN would move a long way.
    model(torch.randn(2, 1, 4, 8, 8) * 50 + 100)

    assert frozen == 1
    assert torch.equal(model[1].running_mean, baseline_mean)
    assert torch.equal(model[1].running_var, baseline_var)


def test_batchnorm_does_drift_without_the_guard():
    """Proves the guard is load-bearing, not decorative."""
    model = nn.Sequential(nn.Conv3d(1, 4, 3, padding=1), nn.BatchNorm3d(4))
    model.train()
    model(torch.randn(8, 1, 4, 8, 8))
    baseline_mean = model[1].running_mean.clone()

    model.train()  # no _freeze_batchnorm here
    model(torch.randn(2, 1, 4, 8, 8) * 50 + 100)

    assert not torch.equal(model[1].running_mean, baseline_mean)


def test_train_re_enables_batchnorm_so_the_guard_must_follow_it():
    """`train()` walks the tree and undoes the guard -- ordering matters."""
    model = nn.Sequential(nn.BatchNorm3d(2))
    _freeze_batchnorm(model)
    assert not model[0].training

    model.train()
    assert model[0].training, "train() is expected to undo the guard"

    _freeze_batchnorm(model)
    assert not model[0].training


# --- Guard 2: replay buffer ------------------------------------------------


def test_replay_dir_is_mixed_into_the_training_set(tmp_path):
    corrections = _write_dataset(tmp_path / "corrections", 5)
    replay = _write_dataset(tmp_path / "replay", 20)

    dataset = build_train_dataset(str(corrections), str(replay), replay_size=200)

    assert len(dataset) == 25


def test_replay_is_capped_at_replay_size(tmp_path):
    corrections = _write_dataset(tmp_path / "corrections", 5)
    replay = _write_dataset(tmp_path / "replay", 50)

    dataset = build_train_dataset(str(corrections), str(replay), replay_size=10)

    assert len(dataset) == 15


def test_replay_sampling_is_reproducible_across_runs(tmp_path):
    corrections = _write_dataset(tmp_path / "corrections", 2)
    replay = _write_dataset(tmp_path / "replay", 30)

    first = build_train_dataset(str(corrections), str(replay), replay_size=5, seed=7)
    second = build_train_dataset(str(corrections), str(replay), replay_size=5, seed=7)
    other = build_train_dataset(str(corrections), str(replay), replay_size=5, seed=8)

    picked = lambda ds: ds.datasets[1].indices  # noqa: E731
    assert picked(first) == picked(second)
    assert picked(first) != picked(other)


def test_no_replay_dir_leaves_corrections_untouched(tmp_path):
    corrections = _write_dataset(tmp_path / "corrections", 5)

    dataset = build_train_dataset(str(corrections), replay_dir=None)

    assert len(dataset) == 5


# --- Guard 3: macro-F1 gate sees what accuracy hides -----------------------


def test_macro_f1_catches_a_severe_collapse_that_accuracy_hides():
    """The exact trap: high accuracy, zero clinical value on the rare class."""
    # 100 Normal, 20 Moderate, 10 Severe -- model predicts Normal for everything.
    collapsed = np.zeros((3, 3), dtype=np.int64)
    collapsed[0][0] = 100
    collapsed[1][0] = 20
    collapsed[2][0] = 10

    per_class = _f1_per_class(collapsed)
    accuracy = np.diag(collapsed).sum() / collapsed.sum()

    assert accuracy > 0.75, "accuracy looks healthy"
    assert per_class[2] == 0.0, "but Severe F1 is zero"
    assert _nanmean(per_class) < 0.32, "and macro-F1 refuses to be fooled"


def test_f1_is_perfect_for_a_perfect_confusion_matrix():
    perfect = np.diag([100, 20, 10]).astype(np.int64)

    per_class = _f1_per_class(perfect)

    assert _nanmean(per_class) == pytest.approx(1.0)


def test_absent_class_is_nan_not_zero():
    """A held-out set this small may simply contain no Severe discs."""
    no_severe = np.zeros((3, 3), dtype=np.int64)
    no_severe[0][0] = 50
    no_severe[1][1] = 10

    per_class = _f1_per_class(no_severe)

    assert np.isnan(per_class[2]), "absent class must not be scored 0"
    assert _nanmean(per_class) == pytest.approx(1.0), "and must not drag the macro down"


def test_nanmean_of_all_nan_is_nan():
    assert np.isnan(_nanmean([float("nan"), float("nan")]))
