"""Pick a small, label-balanced set of RSNA studies to sanity-check grading.

The point of the set is that a person can look at one screen and tell whether
the machine graded correctly. That needs three things side by side: the image,
what the app predicted, and what the radiologist actually wrote. This script
does the first part -- choosing *which* studies are worth looking at.

Two constraints drive the choice.

**Never-trained-on.** `backend/data/holdout_frozen/` froze 200 rows drawn from
the validation patients of the seed-42 patient split (see its MANIFEST.json,
"Never train on these"). Its filepaths carry the study ids, so the studies it
covers are ones the Phase-2 model did not learn. Grading a study the model
trained on would look good for the wrong reason.

**Label spread.** The two sample studies already vendored in `sample_volumes/`
are almost entirely Normal/Mild, so a model that answered "Normal/Mild" to
everything would score ~100% on them and nobody would notice. The set below
deliberately mixes Severe canal, Severe foraminal, and clean studies, so a
constant answer is visibly wrong.

Output: a JSON manifest consumed by `tools/build_validation_set.py`.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

RSNA_DIR = Path(
    "/Users/kienha/spinet-v2/"
    "rsna-2024-lumbar-spine-degenerative-classification"
)
HOLDOUT_META = Path(__file__).resolve().parents[1] / (
    "backend/data/holdout_frozen/train_metadata.csv"
)

LEVELS = ["l1_l2", "l2_l3", "l3_l4", "l4_l5", "l5_s1"]
CONDITIONS = {
    "canal_stenosis": "spinal_canal_stenosis_{lvl}",
    "left_foraminal": "left_neural_foraminal_narrowing_{lvl}",
    "right_foraminal": "right_neural_foraminal_narrowing_{lvl}",
}
# The three conditions the app's own CBAM model answers; the other 8 labels in
# the UI come from upstream SpineNet and have no RSNA ground truth to check.


def held_out_study_ids() -> set[str]:
    """Study ids the frozen holdout covers, i.e. never trained on."""
    ids: set[str] = set()
    with HOLDOUT_META.open() as fh:
        for row in csv.DictReader(fh):
            # filepath looks like "<study_id>/<series_id>_<level>.npy"
            ids.add(row["filepath"].split("/", 1)[0])
    return ids


def load_labels() -> dict[str, dict[str, str]]:
    with (RSNA_DIR / "train.csv").open() as fh:
        return {row["study_id"]: row for row in csv.DictReader(fh)}


def sagittal_t2_series(study_id: str) -> str | None:
    """The series the grading pipeline will actually read, if the study has one."""
    with (RSNA_DIR / "train_series_descriptions.csv").open() as fh:
        for row in csv.DictReader(fh):
            if row["study_id"] != study_id:
                continue
            desc = row["series_description"].upper()
            if "SAG" in desc and ("T2" in desc or "STIR" in desc):
                return row["series_id"]
    return None


def series_of(study_id: str) -> list[tuple[str, str]]:
    out = []
    with (RSNA_DIR / "train_series_descriptions.csv").open() as fh:
        for row in csv.DictReader(fh):
            if row["study_id"] == study_id:
                out.append((row["series_id"], row["series_description"]))
    return out


def cells(label_row: dict[str, str]) -> dict[tuple[str, str], str]:
    """{(condition, level): severity} for the 15 cells the CBAM model answers."""
    out = {}
    for cond, template in CONDITIONS.items():
        for lvl in LEVELS:
            value = (label_row.get(template.format(lvl=lvl)) or "").strip()
            out[(cond, lvl)] = value
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tools/validation_cases.json")
    ap.add_argument("--n-canal", type=int, default=3)
    ap.add_argument("--n-foraminal", type=int, default=3)
    ap.add_argument("--n-normal", type=int, default=2)
    args = ap.parse_args()

    holdout = held_out_study_ids()
    labels = load_labels()
    print(f"holdout studies: {len(holdout)}   labelled studies: {len(labels)}")

    buckets: dict[str, list] = defaultdict(list)
    for study_id in sorted(holdout):
        row = labels.get(study_id)
        if row is None:
            continue
        table = cells(row)
        if any(v == "" for v in table.values()):
            continue  # incomplete ground truth -- can't score it honestly
        if not (RSNA_DIR / "train_images" / study_id).is_dir():
            continue

        canal_sev = sum(
            1 for (c, _), v in table.items()
            if c == "canal_stenosis" and v == "Severe"
        )
        foram_sev = sum(
            1 for (c, _), v in table.items()
            if c.endswith("foraminal") and v == "Severe"
        )
        n_moderate = sum(1 for v in table.values() if v == "Moderate")
        all_normal = all(v == "Normal/Mild" for v in table.values())

        entry = {
            "study_id": study_id,
            "canal_severe": canal_sev,
            "foraminal_severe": foram_sev,
            "moderate": n_moderate,
            "truth": {f"{c}|{lvl}": v for (c, lvl), v in table.items()},
        }
        if canal_sev >= 1:
            buckets["canal"].append(entry)
        elif foram_sev >= 2:
            # 'elif': keep the buckets disjoint so the set covers both failure
            # modes rather than stacking studies that happen to have both.
            buckets["foraminal"].append(entry)
        elif all_normal:
            buckets["normal"].append(entry)

    # Strongest signal first: the more Severe cells, the more obvious a
    # "predicts Normal/Mild for everything" model becomes.
    buckets["canal"].sort(key=lambda e: -e["canal_severe"])
    buckets["foraminal"].sort(key=lambda e: -e["foraminal_severe"])
    buckets["normal"].sort(key=lambda e: e["study_id"])

    chosen = (
        buckets["canal"][: args.n_canal]
        + buckets["foraminal"][: args.n_foraminal]
        + buckets["normal"][: args.n_normal]
    )
    for entry in chosen:
        entry["series"] = [
            {"series_id": sid, "description": desc}
            for sid, desc in series_of(entry["study_id"])
        ]
        entry["grading_series"] = sagittal_t2_series(entry["study_id"])

    missing = [e["study_id"] for e in chosen if not e["grading_series"]]
    if missing:
        print(f"WARNING: no sagittal T2/STIR series for {missing}")

    out_path = Path(args.out)
    out_path.write_text(json.dumps({"cases": chosen}, indent=2))

    print(
        f"\navailable -> canal {len(buckets['canal'])}, "
        f"foraminal {len(buckets['foraminal'])}, normal {len(buckets['normal'])}"
    )
    print(f"chose {len(chosen)} cases -> {out_path}\n")
    for e in chosen:
        print(
            f"  {e['study_id']:>12}  canal_severe={e['canal_severe']} "
            f"foraminal_severe={e['foraminal_severe']} moderate={e['moderate']} "
            f"series={len(e['series'])}"
        )


if __name__ == "__main__":
    main()
