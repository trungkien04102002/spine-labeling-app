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
this repo calls it automatically, and it is not exercised by the test suite
(no GPU / real doctor-correction data available at scaffold time).
"""

from __future__ import annotations

import copy
import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

from models.grading_attention import GradingModelWithCBAM

_HEADS = ("spinal_canal", "left_foraminal", "right_foraminal")


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
    """Mean loss + per-head accuracy over labeled (non -1) examples."""
    model.eval()
    total_loss, num_batches = 0.0, 0
    correct = {h: 0 for h in _HEADS}
    total = {h: 0 for h in _HEADS}

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
                correct[h] += int((preds[mask] == target[mask]).sum().item())
                total[h] += int(mask.sum().item())
        total_loss += float(batch_loss.item())
        num_batches += 1

    acc = {h: (correct[h] / total[h] if total[h] else float("nan")) for h in _HEADS}
    labeled_accs = [v for v in acc.values() if not np.isnan(v)]
    mean_acc = float(np.mean(labeled_accs)) if labeled_accs else float("nan")
    return {
        "loss": total_loss / num_batches if num_batches else float("nan"),
        **{f"acc_{h}": acc[h] for h in _HEADS},
        "mean_acc": mean_acc,
    }


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
) -> RetrainResult:
    """Head-only fine-tune on doctor corrections; keep the result only if it helps.

    Args:
        checkpoint_path: the currently-deployed checkpoint (e.g.
            `models/weights/phase2_cbam.pth`).
        dataset_dir: a `build_finetune_dataset()` output (corrections to train on).
        holdout_dir: a second such directory used ONLY for before/after eval
            (a separate held-out set of corrected/known-good discs -- never
            trained on).
        out_checkpoint: where to write the improved checkpoint, if any.
        epochs, lr, batch_size, patience: kept small/simple by design.
        device: "cpu" or "cuda" (GPU is optional; nothing here requires it).

    Returns:
        A `RetrainResult` with before/after held-out metrics and whether a new
        checkpoint was written (only when held-out `mean_acc` improves).
    """
    train_loader = DataLoader(
        CorrectionDataset(dataset_dir),
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
    best_mean_acc = before["mean_acc"] if not np.isnan(before["mean_acc"]) else -1.0
    best_state = copy.deepcopy(model.state_dict())
    epochs_without_improvement = 0

    for _epoch in range(epochs):
        model.train()
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
            not np.isnan(metrics["mean_acc"]) and metrics["mean_acc"] > best_mean_acc
        )
        if improved_this_epoch:
            best_mean_acc = metrics["mean_acc"]
            best_state = copy.deepcopy(model.state_dict())
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
        if epochs_without_improvement >= patience:
            break

    model.load_state_dict(best_state)
    after = evaluate(model, holdout_loader, device, criteria)
    improved = (not np.isnan(after["mean_acc"])) and (
        np.isnan(before["mean_acc"]) or after["mean_acc"] > before["mean_acc"]
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
    args = parser.parse_args()

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
    )

    print(f"Before: {result.before}")
    print(f"After:  {result.after}")
    if result.improved:
        print(f"Improved -- saved {result.checkpoint_path}")
    else:
        print("No improvement -- checkpoint NOT saved")


if __name__ == "__main__":
    _cli()
