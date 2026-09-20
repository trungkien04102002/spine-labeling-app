"""Put the app's grades next to the radiologist's, one row per cell.

Reads the manifest and the saved grading results, and writes a Markdown report
and a CSV. Only the three conditions the app's own CBAM model answers
(`canal_stenosis`, `left_foraminal`, `right_foraminal`) are scored -- the other
8 labels in the UI come from upstream SpineNet and have no RSNA ground truth,
so scoring them against this dataset would be inventing a number.

    python3 tools/compare_validation_set.py
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

CONDITIONS = ["canal_stenosis", "left_foraminal", "right_foraminal"]
LEVELS = ["l1_l2", "l2_l3", "l3_l4", "l4_l5", "l5_s1"]
SEVERITIES = ["Normal/Mild", "Moderate", "Severe"]

# The app prints levels as "L4-L5" / "L5-S1"; RSNA columns use "l4_l5".
LEVEL_FROM_APP = {"L1-L2": "l1_l2", "L2-L3": "l2_l3", "L3-L4": "l3_l4",
                  "L4-L5": "l4_l5", "L5-S1": "l5_s1"}


def predictions(result: dict) -> dict[tuple[str, str], tuple[str, float]]:
    """{(condition, level): (severity, score)} for the three scored conditions."""
    out = {}
    for item in result.get("grading", []):
        cond = item["condition"]
        if cond not in CONDITIONS:
            continue
        level = LEVEL_FROM_APP.get(item["level"])
        if level is None:
            continue
        out[(cond, level)] = (item["severity"], item.get("score", float("nan")))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="tools/validation_cases.json")
    ap.add_argument("--results", default="data/validation_set/results")
    # The report is a reviewable artifact, so it lives under docs/ (tracked);
    # the zips and raw results stay in data/, which is gitignored.
    ap.add_argument("--out", default="docs/validation/COMPARISON.md")
    ap.add_argument("--csv", default="docs/validation/comparison.csv")
    args = ap.parse_args()

    cases = json.loads((REPO / args.manifest).read_text())["cases"]
    results_dir = REPO / args.results

    rows = []
    md = [
        "# Grading vs. radiologist, on studies the model never trained on",
        "",
        "Eight RSNA studies drawn from `backend/data/holdout_frozen`, whose",
        "MANIFEST marks them as validation-split patients never used for",
        "training. Ground truth is `train.csv` from the RSNA 2024 challenge.",
        "",
        "Only the three conditions the app's fine-tuned CBAM model answers are",
        "scored. The other 8 labels in the UI come from upstream SpineNet, which",
        "this dataset has no ground truth for.",
        "",
        "`=` the app matched the radiologist, `x` it did not.",
        "",
    ]

    for case in cases:
        study_id = case["study_id"]
        path = results_dir / f"{study_id}.grading.json"
        if not path.exists():
            md.append(f"## {study_id} — NOT GRADED YET\n")
            continue
        result = json.loads(path.read_text())
        pred = predictions(result)
        truth = {tuple(k.split("|")): v for k, v in case["truth"].items()}

        kind = (
            "severe canal stenosis" if case["canal_severe"]
            else "severe foraminal narrowing" if case["foraminal_severe"]
            else "normal / mild throughout"
        )
        hits = sum(
            1 for key, value in truth.items()
            if key in pred and pred[key][0] == value
        )
        n = len(truth)
        md += [
            f"## {study_id} — {kind}",
            "",
            f"App study id `VAL-{study_id}` · matched {hits}/{n} cells",
            "",
            "| Level | Canal (app / doctor) | Left foraminal | Right foraminal |",
            "|---|---|---|---|",
        ]
        for level in LEVELS:
            cells = []
            for cond in CONDITIONS:
                want = truth.get((cond, level), "?")
                got, score = pred.get((cond, level), ("(none)", float("nan")))
                mark = "=" if got == want else "x"
                cells.append(f"{got} / {want} {mark}")
                rows.append({
                    "study_id": study_id,
                    "app_study_id": f"VAL-{study_id}",
                    "case_kind": kind,
                    "condition": cond,
                    "level": level,
                    "predicted": got,
                    "ground_truth": want,
                    "score": f"{score:.4f}" if score == score else "",
                    "match": int(got == want),
                })
            label = level.upper().replace("_", "-")
            md.append(f"| {label} | " + " | ".join(cells) + " |")
        md.append("")

    graded = [r for r in rows if r["predicted"] != "(none)"]
    if graded:
        total = len(graded)
        correct = sum(r["match"] for r in graded)
        md += [
            "## Summary",
            "",
            f"Overall: **{correct}/{total} cells correct "
            f"({100 * correct / total:.1f}%)**",
            "",
            "Per condition:",
            "",
            "| Condition | Correct | Cells | Accuracy |",
            "|---|---|---|---|",
        ]
        for cond in CONDITIONS:
            sub = [r for r in graded if r["condition"] == cond]
            if sub:
                ok = sum(r["match"] for r in sub)
                md.append(
                    f"| {cond} | {ok} | {len(sub)} | "
                    f"{100 * ok / len(sub):.1f}% |"
                )
        md += ["", "Per ground-truth severity (does it ever say Severe?):", "",
               "| Ground truth | Correct | Cells | Recall |", "|---|---|---|---|"]
        for sev in SEVERITIES:
            sub = [r for r in graded if r["ground_truth"] == sev]
            if sub:
                ok = sum(r["match"] for r in sub)
                md.append(
                    f"| {sev} | {ok} | {len(sub)} | {100 * ok / len(sub):.1f}% |"
                )
        pred_counts = Counter(r["predicted"] for r in graded)
        md += [
            "",
            "What the app actually predicted, counted: "
            + ", ".join(f"{k} {v}" for k, v in pred_counts.most_common()),
            "",
        ]

    out_path = REPO / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(md))
    csv_path = REPO / args.csv
    if rows:
        with csv_path.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    print(f"wrote {out_path}")
    print(f"wrote {csv_path}  ({len(rows)} rows)")
    if graded:
        print(f"overall {correct}/{total} = {100 * correct / total:.1f}%")


if __name__ == "__main__":
    main()
