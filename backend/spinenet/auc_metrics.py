"""Per-class AUC + AUPRC + Brier helper for RSNA-style multi-task heads.

Shared by:
- ``eval_rsna_auc.py``       : standalone post-hoc eval on existing checkpoints
- ``train_rsna_baseline.py`` : training-time eval each epoch
- ``train_rsna_attention.py`` : training-time eval each epoch
- ``train_rsna_hybrid.py``    : training-time eval each epoch

Why these three metrics together
--------------------------------
* **AUC (ROC)** is insensitive to class imbalance — useful as a generic
  ranking metric but can be misleadingly high on a minority class.
* **AUPRC** (Average Precision under PR-curve) is the imbalance-friendly
  cousin: it directly measures performance on the positive class. For RSNA's
  ~5 % Severe rate, AUPRC is the metric that actually moves when the model
  learns Severe vs. when it just memorises the prior. **Use AUPRC, not AUC,
  to argue rare-class improvement.**
* **Brier score** is the calibration sanity-check (mean squared error of
  probabilities). A high AUPRC with a high Brier score = correct ranking
  but mis-calibrated confidence — flag for downstream calibration work.

Each metric is computed one-vs-rest per class. ``-1`` labels (missing
annotations) are filtered out before computation.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
)


CLASS_NAMES_DEFAULT = ["Normal/Mild", "Moderate", "Severe"]


def compute_auc_auprc_per_condition(
    probs_dict: Dict[str, np.ndarray],
    labels_dict: Dict[str, np.ndarray],
    class_names: Optional[List[str]] = None,
) -> Dict[str, dict]:
    """Per-class AUC / AUPRC / Brier for each condition (one-vs-rest).

    Args:
        probs_dict:  ``{cond_name: probs[N, C]}`` — softmax probabilities.
        labels_dict: ``{cond_name: labels[N]}``  — int labels in ``[0, C-1]``,
            or ``-1`` for missing.
        class_names: Display names for the C classes; defaults to RSNA's
            ``["Normal/Mild", "Moderate", "Severe"]``.

    Returns:
        ``{cond: {"per_class": {name: {auc, auprc, brier, support}, ...},
                   "macro_auc": float, "macro_auprc": float}}``

        Macro averages skip classes that returned NaN (zero or full
        support — AUC/AUPRC undefined).
    """
    names = class_names or CLASS_NAMES_DEFAULT
    out: Dict[str, dict] = {}
    for cond, probs in probs_dict.items():
        labels = labels_dict[cond]
        valid = labels != -1
        probs, labels = probs[valid], labels[valid]
        per_class: Dict[str, dict] = {}
        aucs: List[float] = []
        auprcs: List[float] = []

        for c, name in enumerate(names):
            y = (labels == c).astype(int)
            s = probs[:, c]
            support = int(y.sum())
            n = len(y)

            if n == 0 or support == 0 or support == n:
                auc = float("nan")
                auprc = float("nan")
            else:
                auc = float(roc_auc_score(y, s))
                auprc = float(average_precision_score(y, s))
            brier = float(brier_score_loss(y, s)) if support > 0 else float("nan")

            per_class[name] = {
                "auc": auc,
                "auprc": auprc,
                "brier": brier,
                "support": support,
            }
            if not np.isnan(auc):
                aucs.append(auc)
            if not np.isnan(auprc):
                auprcs.append(auprc)

        out[cond] = {
            "per_class": per_class,
            "macro_auc": float(np.mean(aucs)) if aucs else float("nan"),
            "macro_auprc": float(np.mean(auprcs)) if auprcs else float("nan"),
        }
    return out


def aggregate_overall_auprc(
    auc_auprc_metrics: Dict[str, dict],
    class_names: Optional[List[str]] = None,
) -> dict:
    """Pop / Rare / Severe AUPRC + AUC averaged across conditions.

    Mirrors the popular-vs-rare framing used in the report's Bảng 1C.
    """
    names = class_names or CLASS_NAMES_DEFAULT
    popular = [names[0]]
    rare = names[1:]
    severe = [names[-1]]

    def _mean(metric: str, classes: List[str]) -> float:
        vals: List[float] = []
        for cond, payload in auc_auprc_metrics.items():
            for cls in classes:
                v = payload["per_class"].get(cls, {}).get(metric, float("nan"))
                if not np.isnan(v):
                    vals.append(v)
        return float(np.mean(vals)) if vals else float("nan")

    macro_aucs = [m["macro_auc"] for m in auc_auprc_metrics.values()
                  if not np.isnan(m["macro_auc"])]
    macro_auprcs = [m["macro_auprc"] for m in auc_auprc_metrics.values()
                    if not np.isnan(m["macro_auprc"])]

    return {
        "macro_auc": float(np.mean(macro_aucs)) if macro_aucs else float("nan"),
        "macro_auprc": float(np.mean(macro_auprcs)) if macro_auprcs else float("nan"),
        "popular_auc":   _mean("auc",   popular),
        "popular_auprc": _mean("auprc", popular),
        "rare_auc":      _mean("auc",   rare),
        "rare_auprc":    _mean("auprc", rare),
        "severe_auc":    _mean("auc",   severe),
        "severe_auprc":  _mean("auprc", severe),
    }
