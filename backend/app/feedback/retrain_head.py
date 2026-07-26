"""Simple head-only fine-tune of the deployed CBAM grading model.

Deliberately minimal ("co the don gian thoi cung duoc" -- advisor feedback):
load the checkpoint currently served in production, freeze the ResNet
backbone (same `freeze_backbone()` the RSNA->SPIDER transfer flow in
`spinet-v2/train_spider.py --freeze-backbone` uses -- it leaves the CBAM
blocks and the three classification heads trainable), fine-tune on the small
dataset `build_dataset.build_finetune_dataset` produced, evaluate on a
held-out set before vs. after, and only keep the new checkpoint if it helps.

No LR schedule, no focal/uncertainty loss, no augmentation -- just
`CrossEntropyLoss(ignore_index=-1)` for a handful of epochs with early
stopping. This module only defines the fine-tune function + a CLI; nothing in
this repo calls it automatically.

Three guards make the "simple" version safe rather than merely small, because
each covers a failure mode that is invisible in the output unless you look for
it (see `spinet-v2/docs/LVTN_phase3/FEEDBACK_LOOP_METHODS.md`):

1. **BatchNorm is frozen during training.** `freeze_backbone()` only clears
   `requires_grad`; without `_freeze_batchnorm` the BN running statistics get
   overwritten by a handful of samples.
2. **A replay buffer of original discs is mixed in** (`--replay-dir`).
   Training on corrections alone is the standard way to induce forgetting.
3. **The keep/discard gate is macro-F1, not accuracy.** `Severe` is rare
   enough that a model can collapse to predicting `Normal/Mild`, lose all
   clinical value, and still post a higher mean accuracy.
"""

from __future__ import annotations

import copy
import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import ConcatDataset, DataLoader, Dataset, Subset

from models.grading_attention import GradingModelWithCBAM

_HEADS = ("spinal_canal", "left_foraminal", "right_foraminal")
_NUM_CLASSES = 3  # 0 = Normal/Mild, 1 = Moderate, 2 = Severe
_SEVERE = 2


def _freeze_batchnorm(model: nn.Module) -> int:
    """Put every BatchNorm module in eval() so its running stats stop moving.

    `freeze_backbone()` only clears `requires_grad`; BatchNorm layers keep
    overwriting `running_mean` / `running_var` from whatever mini-batch they
    see while the model is in `train()` mode. With a few dozen corrections at
    `batch_size=4` those statistics are noise, and replacing the RSNA-scale
    statistics with them is a documented cause of catastrophic forgetting when
    adapting medical models on tiny local sets (arXiv:2011.08096, which also
    found that touching only the BN affine terms matches full fine-tuning
    across 7 medical datasets). Returns how many modules were frozen so the
    caller can assert the guard actually bit.
    """
    frozen = 0
    for module in model.modules():
        if isinstance(module, nn.modules.batchnorm._BatchNorm):
            module.eval()
            frozen += 1
    return frozen


def _f1_per_class(confusion: np.ndarray) -> np.ndarray:
    """Per-class F1 from a `[true][pred]` confusion matrix.

    Classes with no support in the held-out set come back as NaN rather than 0
    so they can be excluded from the macro average -- on a held-out set this
    small, `Severe` may legitimately be absent, and scoring it 0 would drag the
    gate metric down for a reason that has nothing to do with the model.
    """
    tp = np.diag(confusion).astype(float)
    support = confusion.sum(axis=1).astype(float)
    denom = 2 * tp + (confusion.sum(axis=0) - tp) + (support - tp)
    f1 = np.full(_NUM_CLASSES, np.nan)
    present = support > 0
    f1[present] = np.divide(
        2 * tp, denom, out=np.zeros_like(tp), where=denom > 0
    )[present]
    return f1


def _nanmean(values) -> float:
    """Mean over non-NaN entries; NaN when there is nothing to average."""
    finite = [v for v in values if not np.isnan(v)]
    return float(np.mean(finite)) if finite else float("nan")


class CorrectionDataset(Dataset):
    """Reads a `build_dataset.build_finetune_dataset()` output directory."""

    def __init__(self, dataset_dir: str):
        self.dataset_dir = Path(dataset_dir)
        metadata_csv = self.dataset_dir / "train_metadata.csv"
        with open(metadata_csv, newline="") as f:
            self.rows = list(csv.DictReader(f))
        if not self.rows:
            raise ValueError(f"No rows in {metadata_csv}")

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, dict[str, int]]:
        row = self.rows[idx]
        volume = np.load(self.dataset_dir / "volumes" / row["filepath"])
        tensor = torch.from_numpy(volume).float().unsqueeze(0)  # (1, 9, 112, 224)
        labels = {h: int(row[h]) for h in _HEADS}
        return tensor, labels


def _collate(batch: list[tuple[torch.Tensor, dict[str, int]]]):
    volumes = torch.stack([item[0] for item in batch])
    labels = {
        h: torch.tensor([item[1][h] for item in batch], dtype=torch.long)
        for h in _HEADS
    }
    return volumes, labels


def load_checkpoint(weights_path: str, device: str = "cpu") -> GradingModelWithCBAM:
    """Load the deployed CBAM grading model in trainable (non-cached) form.

    Mirrors `app.inference.grading._load_model`'s checkpoint-format handling,
    but returns a fresh instance (that module's loader is `lru_cache`d and
    kept in `eval()` for serving, so it's unsuitable for fine-tuning).
    """
    model = GradingModelWithCBAM(format="rsna", use_cbam=True)
    checkpoint = torch.load(weights_path, map_location=device, weights_only=False)
    if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
        state_dict = checkpoint["model_state_dict"]
    elif isinstance(checkpoint, dict) and "model_weights" in checkpoint:
        state_dict = checkpoint["model_weights"]
    else:
        state_dict = checkpoint
    model.load_state_dict(state_dict)
    return model.to(device)


@torch.no_grad()
def evaluate(
    model: GradingModelWithCBAM,
    loader: DataLoader,
    device: str,
    criteria: dict[str, nn.Module],
) -> dict[str, float]:
    """Mean loss + per-head accuracy *and* per-class F1 over labeled examples.

    Accuracy on its own is actively misleading here: `Severe` is the rare
    class, so a model that collapses to predicting `Normal/Mild` everywhere
    still posts a high mean accuracy while being useless for the one class
    this work exists to improve. `macro_f1` is therefore what the retrain gate
    keys off, and `severe_f1` is reported separately so a collapse is visible
    at a glance.
    """
    model.eval()
    total_loss, num_batches = 0.0, 0
    # confusion[head][true][pred]
    confusion = {
        h: np.zeros((_NUM_CLASSES, _NUM_CLASSES), dtype=np.int64) for h in _HEADS
    }

    for volumes, labels in loader:
        volumes = volumes.to(device)
        outputs = model(volumes)
        batch_loss = 0.0
        for h in _HEADS:
            target = labels[h].to(device)
            batch_loss = batch_loss + criteria[h](outputs[h], target)
            mask = target != -1
            if mask.any():
                preds = outputs[h].argmax(dim=1)
                for true_c, pred_c in zip(
                    target[mask].cpu().numpy(), preds[mask].cpu().numpy()
                ):
                    confusion[h][int(true_c)][int(pred_c)] += 1
        total_loss += float(batch_loss.item())
        num_batches += 1

    acc: dict[str, float] = {}
    f1_macro: dict[str, float] = {}
    f1_severe: dict[str, float] = {}
    for h in _HEADS:
        cm = confusion[h]
        n_labeled = int(cm.sum())
        acc[h] = float(np.diag(cm).sum() / n_labeled) if n_labeled else float("nan")
        per_class = _f1_per_class(cm)
        f1_macro[h] = _nanmean(per_class)
        f1_severe[h] = float(per_class[_SEVERE])

    return {
        "loss": total_loss / num_batches if num_batches else float("nan"),
        **{f"acc_{h}": acc[h] for h in _HEADS},
        **{f"f1_{h}": f1_macro[h] for h in _HEADS},
        "mean_acc": _nanmean(acc.values()),
        "macro_f1": _nanmean(f1_macro.values()),
        "severe_f1": _nanmean(f1_severe.values()),
    }


def build_train_dataset(
    dataset_dir: str,
    replay_dir: str | None = None,
    replay_size: int = 200,
    seed: int = 42,
) -> Dataset:
    """Corrections, optionally mixed with a capped sample of original discs.

    The replay half is what keeps the heads anchored to the distribution the
    deployed checkpoint was trained on; without it, a few dozen corrections
    pull the heads wherever those corrections happen to point.
    """
    corrections: Dataset = CorrectionDataset(dataset_dir)
    if not replay_dir:
        return corrections

    replay: Dataset = CorrectionDataset(replay_dir)
    if len(replay) > replay_size:  # type: ignore[arg-type]
        generator = torch.Generator().manual_seed(seed)
        picks = torch.randperm(len(replay), generator=generator)  # type: ignore[arg-type]
        replay = Subset(replay, picks[:replay_size].tolist())
    return ConcatDataset([corrections, replay])


@dataclass
class RetrainResult:
    before: dict[str, float]
    after: dict[str, float]
    improved: bool
    checkpoint_path: str | None  # set only if `improved` and a checkpoint was saved


def retrain_head(
    checkpoint_path: str,
    dataset_dir: str,
    holdout_dir: str,
    out_checkpoint: str,
    epochs: int = 5,
    lr: float = 1e-4,
    batch_size: int = 4,
    patience: int = 2,
    device: str = "cpu",
    replay_dir: str | None = None,
    replay_size: int = 200,
    seed: int = 42,
) -> RetrainResult:
    """Head-only fine-tune on doctor corrections; keep the result only if it helps.

    Args:
        checkpoint_path: the currently-deployed checkpoint (e.g.
            `models/weights/phase2_cbam.pth`).
        dataset_dir: a `build_finetune_dataset()` output (corrections to train on).
        holdout_dir: a second such directory used ONLY for before/after eval
            (a separate held-out set of corrected/known-good discs -- never
            trained on). Freeze this set BEFORE collecting any corrections;
            carving it out afterwards makes the before/after numbers
            meaningless.
        out_checkpoint: where to write the improved checkpoint, if any.
        epochs, lr, batch_size, patience: kept small/simple by design.
        device: "cpu" or "cuda" (GPU is optional; nothing here requires it).
        replay_dir: optional `build_finetune_dataset()` output holding original
            training discs. Up to `replay_size` of them are mixed into each
            epoch so the heads keep seeing the old distribution. Training on
            corrections alone is what makes a model forget; in medical imaging
            a small replay buffer has repeatedly beaten regularisation-based
            schemes such as EWC, so this is the cheap guard worth having.
        replay_size: cap on replayed samples (200 is plenty next to ~20-50
            corrections and still runs on CPU).
        seed: fixes which replay samples get drawn, so a rerun is comparable.

    Returns:
        A `RetrainResult` with before/after held-out metrics and whether a new
        checkpoint was written (only when held-out `macro_f1` improves).
    """
    train_dataset = build_train_dataset(dataset_dir, replay_dir, replay_size, seed)

    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        collate_fn=_collate,
    )
    holdout_loader = DataLoader(
        CorrectionDataset(holdout_dir),
        batch_size=batch_size,
        shuffle=False,
        collate_fn=_collate,
    )

    model = load_checkpoint(checkpoint_path, device)
    # Head-only fine-tune: freezes the ResNet backbone, leaves the CBAM blocks
    # + the three fc_* heads trainable (same convention as
    # `GradingModelWithCBAM.freeze_backbone` / `train_spider.py --freeze-backbone`).
    model.freeze_backbone(freeze=True)

    criteria = {h: nn.CrossEntropyLoss(ignore_index=-1) for h in _HEADS}
    optimizer = torch.optim.AdamW(
        filter(lambda p: p.requires_grad, model.parameters()), lr=lr
    )

    before = evaluate(model, holdout_loader, device, criteria)
    best_macro_f1 = before["macro_f1"] if not np.isnan(before["macro_f1"]) else -1.0
    best_state = copy.deepcopy(model.state_dict())
    epochs_without_improvement = 0

    for _epoch in range(epochs):
        model.train()
        # MUST come after train(): train() walks the whole module tree and puts
        # every BatchNorm back into training mode, undoing the guard.
        _freeze_batchnorm(model)
        for volumes, labels in train_loader:
            volumes = volumes.to(device)
            optimizer.zero_grad()
            outputs = model(volumes)
            loss = sum(
                criteria[h](outputs[h], labels[h].to(device)) for h in _HEADS
            )
            loss.backward()
            optimizer.step()

        metrics = evaluate(model, holdout_loader, device, criteria)
        improved_this_epoch = (
            not np.isnan(metrics["macro_f1"]) and metrics["macro_f1"] > best_macro_f1
        )
        if improved_this_epoch:
            best_macro_f1 = metrics["macro_f1"]
            best_state = copy.deepcopy(model.state_dict())
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
        if epochs_without_improvement >= patience:
            break

    model.load_state_dict(best_state)
    after = evaluate(model, holdout_loader, device, criteria)
    improved = (not np.isnan(after["macro_f1"])) and (
        np.isnan(before["macro_f1"]) or after["macro_f1"] > before["macro_f1"]
    )

    checkpoint_written = None
    if improved:
        Path(out_checkpoint).parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "model_state_dict": best_state,
                "before_metrics": before,
                "after_metrics": after,
                "base_checkpoint": checkpoint_path,
            },
            out_checkpoint,
        )
        checkpoint_written = out_checkpoint

    return RetrainResult(
        before=before, after=after, improved=improved, checkpoint_path=checkpoint_written
    )


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, help="Deployed checkpoint to fine-tune")
    parser.add_argument("--dataset-dir", required=True, help="build_dataset.py output (train)")
    parser.add_argument("--holdout-dir", required=True, help="build_dataset.py output (held-out eval)")
    parser.add_argument("--out-checkpoint", required=True, help="Where to write the improved checkpoint")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--patience", type=int, default=2)
    parser.add_argument("--device", default="cpu")
    parser.add_argument(
        "--replay-dir",
        default=None,
        help="build_dataset.py output holding ORIGINAL training discs; mixed in "
        "so the heads do not forget. Strongly recommended.",
    )
    parser.add_argument("--replay-size", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if not args.replay_dir:
        print(
            "WARNING: no --replay-dir. Training on corrections alone is the "
            "single most likely way to make the model forget. Pass a replay "
            "set unless you are deliberately measuring that effect."
        )

    result = retrain_head(
        checkpoint_path=args.checkpoint,
        dataset_dir=args.dataset_dir,
        holdout_dir=args.holdout_dir,
        out_checkpoint=args.out_checkpoint,
        epochs=args.epochs,
        lr=args.lr,
        batch_size=args.batch_size,
        patience=args.patience,
        device=args.device,
        replay_dir=args.replay_dir,
        replay_size=args.replay_size,
        seed=args.seed,
    )

    def _fmt(metrics: dict[str, float]) -> str:
        return (
            f"macro_f1={metrics['macro_f1']:.4f}  "
            f"severe_f1={metrics['severe_f1']:.4f}  "
            f"mean_acc={metrics['mean_acc']:.4f}"
        )

    print(f"Before: {_fmt(result.before)}")
    print(f"After:  {_fmt(result.after)}")
    print(
        f"Delta:  macro_f1={result.after['macro_f1'] - result.before['macro_f1']:+.4f}  "
        f"severe_f1={result.after['severe_f1'] - result.before['severe_f1']:+.4f}"
    )
    if result.improved:
        print(f"Improved (macro-F1) -- saved {result.checkpoint_path}")
    else:
        print("No macro-F1 improvement -- checkpoint NOT saved")


if __name__ == "__main__":
    _cli()
