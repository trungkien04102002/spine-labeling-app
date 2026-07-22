"""
Persist training/eval metrics to disk alongside model checkpoints.

Why this exists:
    .pth checkpoints don't store the per-class F1 / recall / support breakdown
    we need for paper tables. Re-running evaluation to recover them is slow.
    This logger writes:
        {save_dir}/{prefix}_log.csv          -- one row per epoch
        {save_dir}/{prefix}_best_metrics.json -- machine-readable best snapshot
        {save_dir}/{prefix}_best_metrics.txt  -- human-readable best snapshot

Usage:
    logger = MetricsLogger(save_dir="checkpoints/", prefix="attention")
    logger.log_epoch(epoch, train_loss, val_loss, val_accuracies,
                     per_class_metrics=..., avg_severe_f1=..., is_best=True)
    if is_best:
        logger.save_best(epoch, train_loss, val_loss, val_accuracies,
                         per_class_metrics=..., avg_severe_f1=..., extra={...})
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


CLASS_NAMES = ["Normal/Mild", "Moderate", "Severe"]


def _to_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def _list_of_floats(x):
    if x is None:
        return []
    if hasattr(x, "tolist"):
        x = x.tolist()
    return [float(v) for v in x]


def _is_nan(x) -> bool:
    """NaN check that survives None / strings."""
    try:
        return x != x  # NaN is the only float that is not equal to itself
    except Exception:
        return True


class MetricsLogger:
    def __init__(self, save_dir, prefix: str):
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.prefix = prefix
        self.log_csv = self.save_dir / f"{prefix}_log.csv"
        self.best_json = self.save_dir / f"{prefix}_best_metrics.json"
        self.best_txt = self.save_dir / f"{prefix}_best_metrics.txt"
        self._csv_initialized = self.log_csv.exists()

    def log_epoch(
        self,
        epoch: int,
        train_loss: float,
        val_loss: float,
        val_accuracies: Dict[str, float],
        per_class_metrics: Optional[Dict[str, Dict[str, Any]]] = None,
        avg_severe_f1: Optional[float] = None,
        is_best: bool = False,
        extra: Optional[Dict[str, Any]] = None,
        auc_auprc_metrics: Optional[Dict[str, Dict[str, Any]]] = None,
        auc_auprc_overall: Optional[Dict[str, float]] = None,
    ) -> None:
        """Append one row to {prefix}_log.csv."""
        row = {
            "epoch": int(epoch),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "train_loss": _to_float(train_loss),
            "val_loss": _to_float(val_loss),
            "is_best": int(bool(is_best)),
        }

        for cond in ("spinal_canal", "left_foraminal", "right_foraminal"):
            row[f"acc_{cond}"] = _to_float(val_accuracies.get(cond, float("nan")))

        row["avg_severe_f1"] = (
            _to_float(avg_severe_f1) if avg_severe_f1 is not None else float("nan")
        )

        if per_class_metrics:
            for cond, m in per_class_metrics.items():
                f1 = _list_of_floats(m.get("f1"))
                recall = _list_of_floats(m.get("recall"))
                if len(f1) >= 3:
                    row[f"severe_f1_{cond}"] = f1[2]
                if len(recall) >= 3:
                    row[f"severe_recall_{cond}"] = recall[2]

        # Per-epoch AUC / AUPRC tracking — keep CSV columns minimal: per-cond
        # macro AUC + macro AUPRC + overall severe AUPRC. Full per-class AUC
        # only goes to best_metrics.json/.txt to avoid CSV column blow-up.
        if auc_auprc_metrics:
            for cond in ("spinal_canal", "left_foraminal", "right_foraminal"):
                m = auc_auprc_metrics.get(cond)
                if m:
                    row[f"macro_auc_{cond}"] = _to_float(m.get("macro_auc", float("nan")))
                    row[f"macro_auprc_{cond}"] = _to_float(m.get("macro_auprc", float("nan")))
        if auc_auprc_overall:
            row["overall_macro_auprc"] = _to_float(auc_auprc_overall.get("macro_auprc", float("nan")))
            row["overall_severe_auprc"] = _to_float(auc_auprc_overall.get("severe_auprc", float("nan")))

        if extra:
            for k, v in extra.items():
                row[f"extra_{k}"] = v

        existed = self.log_csv.exists() and self.log_csv.stat().st_size > 0
        with open(self.log_csv, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(row.keys()))
            if not existed:
                writer.writeheader()
            writer.writerow(row)

        severe_str = (
            f"{row['avg_severe_f1']:.4f}"
            if row.get("avg_severe_f1") == row.get("avg_severe_f1")  # not NaN
            else "N/A"
        )
        marker = " (BEST)" if is_best else ""
        print(
            f"  ✓ Logged epoch {epoch} -> {self.log_csv.name} | "
            f"val_loss={row['val_loss']:.4f}, avg_severe_f1={severe_str}{marker}"
        )

    def save_best(
        self,
        epoch: int,
        train_loss: float,
        val_loss: float,
        val_accuracies: Dict[str, float],
        per_class_metrics: Optional[Dict[str, Dict[str, Any]]] = None,
        avg_severe_f1: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
        auc_auprc_metrics: Optional[Dict[str, Dict[str, Any]]] = None,
        auc_auprc_overall: Optional[Dict[str, float]] = None,
    ) -> None:
        """Overwrite {prefix}_best_metrics.json + .txt with current snapshot.

        ``auc_auprc_metrics`` is the dict returned by
        ``spinenet.auc_metrics.compute_auc_auprc_per_condition``; pass it to
        record AUC/AUPRC/Brier alongside the existing argmax metrics.
        ``auc_auprc_overall`` is the result of ``aggregate_overall_auprc`` —
        the popular/rare/Severe roll-up across conditions.
        """
        clean_per_class: Dict[str, Dict[str, Any]] = {}
        if per_class_metrics:
            for cond, m in per_class_metrics.items():
                clean_per_class[cond] = {
                    "precision": _list_of_floats(m.get("precision")),
                    "recall": _list_of_floats(m.get("recall")),
                    "f1": _list_of_floats(m.get("f1")),
                    "support": [int(s) for s in _list_of_floats(m.get("support"))],
                }

        data = {
            "prefix": self.prefix,
            "epoch": int(epoch),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "train_loss": _to_float(train_loss),
            "val_loss": _to_float(val_loss),
            "val_accuracies": {k: _to_float(v) for k, v in val_accuracies.items()},
            "avg_severe_f1": (
                _to_float(avg_severe_f1) if avg_severe_f1 is not None else None
            ),
            "per_class_metrics": clean_per_class,
            "auc_auprc_metrics": auc_auprc_metrics or {},
            "auc_auprc_overall": auc_auprc_overall or {},
            "extra": extra or {},
        }

        with open(self.best_json, "w") as f:
            json.dump(data, f, indent=2)

        severe_str = (
            f"{data['avg_severe_f1']:.4f}" if data["avg_severe_f1"] is not None else "N/A"
        )
        print(
            f"  ✓ Saved best metrics @ epoch {epoch}: "
            f"val_loss={data['val_loss']:.4f}, avg_severe_f1={severe_str} "
            f"-> {self.best_json.name} + {self.best_txt.name}"
        )

        with open(self.best_txt, "w") as f:
            f.write(f"=== BEST MODEL METRICS ({self.prefix}) ===\n")
            f.write(f"Saved at:  {data['timestamp']}\n")
            f.write(f"Epoch:     {epoch}\n")
            f.write(f"Train Loss: {data['train_loss']:.4f}\n")
            f.write(f"Val Loss:   {data['val_loss']:.4f}\n")
            if avg_severe_f1 is not None:
                f.write(f"Avg Severe F1: {data['avg_severe_f1']:.4f}\n")

            f.write("\nValidation Accuracies:\n")
            for k, v in val_accuracies.items():
                f.write(f"  {k:18s} {_to_float(v):.4f}\n")

            if clean_per_class:
                f.write("\nPer-Class Metrics:\n")
                for cond, m in clean_per_class.items():
                    f.write(f"\n  {cond}:\n")
                    f.write(
                        f"    {'Class':14s}  {'Prec':>6s} {'Recall':>6s} {'F1':>6s} {'Support':>8s}\n"
                    )
                    for i, name in enumerate(CLASS_NAMES):
                        if i < len(m["f1"]):
                            f.write(
                                f"    {name:14s}  "
                                f"{m['precision'][i]:6.3f} "
                                f"{m['recall'][i]:6.3f} "
                                f"{m['f1'][i]:6.3f} "
                                f"{m['support'][i]:8d}\n"
                            )

            if auc_auprc_metrics:
                f.write("\nAUC / AUPRC / Brier (per class, one-vs-rest):\n")
                for cond, m in auc_auprc_metrics.items():
                    f.write(f"\n  {cond}:\n")
                    f.write(
                        f"    {'Class':14s}  {'AUC':>6s} {'AUPRC':>6s} {'Brier':>6s} {'Support':>8s}\n"
                    )
                    for name in CLASS_NAMES:
                        r = m.get("per_class", {}).get(name)
                        if not r:
                            continue
                        auc_s = "  nan " if _is_nan(r["auc"]) else f"{r['auc']:6.3f}"
                        ap_s = "  nan " if _is_nan(r["auprc"]) else f"{r['auprc']:6.3f}"
                        br_s = "  nan " if _is_nan(r["brier"]) else f"{r['brier']:6.3f}"
                        f.write(
                            f"    {name:14s}  {auc_s} {ap_s} {br_s} {r['support']:8d}\n"
                        )
                    f.write(
                        f"    {'macro':14s}  {m['macro_auc']:6.3f} {m['macro_auprc']:6.3f}\n"
                    )

            if auc_auprc_overall:
                f.write("\nAUC / AUPRC overall (averaged across 3 conditions):\n")
                fmt = lambda x: "nan" if _is_nan(x) else f"{x:.3f}"
                f.write(f"  macro AUC      : {fmt(auc_auprc_overall.get('macro_auc'))}\n")
                f.write(f"  macro AUPRC    : {fmt(auc_auprc_overall.get('macro_auprc'))}\n")
                f.write(f"  popular AUPRC  : {fmt(auc_auprc_overall.get('popular_auprc'))}  (Normal/Mild)\n")
                f.write(f"  rare    AUPRC  : {fmt(auc_auprc_overall.get('rare_auprc'))}  (Moderate + Severe)\n")
                f.write(f"  Severe  AUPRC  : {fmt(auc_auprc_overall.get('severe_auprc'))}  (clinical priority)\n")

            if extra:
                f.write("\nExtra:\n")
                for k, v in extra.items():
                    f.write(f"  {k}: {v}\n")
