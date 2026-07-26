"""Carve out and lock an evaluation set BEFORE any corrections are collected.

This has a deadline that no amount of later work can recover. A before/after
comparison only means something if the evaluation set was fixed in advance --
choose it afterwards, once you have seen which discs the doctors corrected, and
the numbers measure your selection rather than the model. There is no way to
reconstruct that guarantee retroactively, so this runs once, early, and writes
a manifest that can be shown to have predated the first correction.

The manifest records a SHA-256 over the selected rows plus the timestamp and
the seed, so the set can be verified as unchanged later:

    python -m app.feedback.freeze_holdout --verify data/holdout_frozen

Output is shaped like `build_dataset.build_finetune_dataset()` output
(`volumes/` + `train_metadata.csv`), so it drops straight into
`retrain_head --holdout-dir`.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np

_HEADS = ("spinal_canal", "left_foraminal", "right_foraminal")
_MANIFEST = "MANIFEST.json"


def _digest(rows: list[dict]) -> str:
    """Stable hash over the selected rows, independent of dict ordering."""
    canonical = json.dumps(
        [{k: str(r[k]) for k in ("filepath", *_HEADS)} for r in rows],
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _read_metadata(source_dir: Path) -> list[dict]:
    metadata_csv = source_dir / "train_metadata.csv"
    if not metadata_csv.is_file():
        raise FileNotFoundError(f"No train_metadata.csv under {source_dir}")
    with open(metadata_csv, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"{metadata_csv} has no rows")
    missing = [h for h in _HEADS if h not in rows[0]]
    if missing:
        raise ValueError(f"{metadata_csv} is missing label columns: {missing}")
    return rows


def _stratify_key(row: dict) -> tuple:
    """Group rows by their label combination so rare grades survive sampling."""
    return tuple(row[h] for h in _HEADS)


def _validation_patients(rows: list[dict], split_seed: int, val_split: float) -> set[str]:
    """The patients a model trained with this seed never saw.

    Reproduces `train_test_split(unique_patients, test_size=val_split,
    random_state=split_seed)` -- the identical call every training script in
    spinet-v2 makes -- so "held out" means held out from the model actually
    being evaluated, not merely held out from this script.
    """
    from sklearn.model_selection import train_test_split

    patients = sorted({row["study_id"] for row in rows})
    # sorted() first: dict/CSV order must not change which patients land in val.
    _, val_patients = train_test_split(
        np.array(patients), test_size=val_split, random_state=split_seed
    )
    return set(val_patients.tolist())


def freeze_holdout(
    source_dir: str,
    out_dir: str,
    n: int = 150,
    seed: int = 42,
    split_seed: int | None = None,
    val_split: float = 0.2,
) -> dict:
    """Sample `n` rows, copy their crops, and write a tamper-evident manifest.

    Sampling is stratified over the label combination: `Severe` is rare enough
    that a uniform draw can miss it entirely, which would leave the evaluation
    blind to the exact class the work is about.

    Args:
        split_seed: restrict the draw to the validation patients of
            `train_test_split(..., random_state=split_seed)`. Pass the seed the
            deployed model was trained with (42 for the shipped checkpoint).
            Without it, most of the source is data the model already fit, and a
            before/after comparison on it measures memorisation rather than
            improvement. Requires a `study_id` column.

    Raises:
        FileExistsError: if `out_dir` already holds a manifest. Re-freezing
            would silently invalidate every comparison already made against
            the old set, so it has to be an explicit, manual decision.
    """
    source = Path(source_dir)
    out = Path(out_dir)
    if (out / _MANIFEST).exists():
        raise FileExistsError(
            f"{out / _MANIFEST} already exists -- this set is already frozen. "
            "Delete it by hand if you really mean to re-freeze; every "
            "before/after number measured against the old set becomes "
            "incomparable."
        )

    rows = _read_metadata(source)
    held_out_from = None
    if split_seed is not None:
        if "study_id" not in rows[0]:
            raise ValueError(
                "--split-seed needs a study_id column to reproduce the "
                "patient-level train/val split."
            )
        val_patients = _validation_patients(rows, split_seed, val_split)
        rows = [row for row in rows if row["study_id"] in val_patients]
        held_out_from = {
            "split_seed": split_seed,
            "val_split": val_split,
            "val_patients": len(val_patients),
            "candidate_rows": len(rows),
        }
        if not rows:
            raise ValueError(
                f"No rows left after restricting to the seed-{split_seed} "
                "validation patients."
            )
    if n >= len(rows):
        raise ValueError(
            f"Asked for {n} held-out rows but the source only has {len(rows)}. "
            "The held-out set must be a strict subset -- leave rows to train on."
        )

    # Stratified round-robin: walk the label groups repeatedly, taking one row
    # from each, so every combination present in the source is represented
    # before any group contributes a second row.
    rng = np.random.default_rng(seed)
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        groups.setdefault(_stratify_key(row), []).append(row)
    for group in groups.values():
        rng.shuffle(group)

    selected: list[dict] = []
    order = sorted(groups)
    while len(selected) < n:
        took_any = False
        for key in order:
            if groups[key]:
                selected.append(groups[key].pop())
                took_any = True
                if len(selected) == n:
                    break
        if not took_any:
            break

    volumes_out = out / "volumes"
    volumes_out.mkdir(parents=True, exist_ok=True)
    for row in selected:
        src_crop = source / "volumes" / row["filepath"]
        dst_crop = volumes_out / row["filepath"]
        dst_crop.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_crop, dst_crop)

    with open(out / "train_metadata.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["filepath", *_HEADS])
        writer.writeheader()
        writer.writerows({k: row[k] for k in ("filepath", *_HEADS)} for row in selected)

    label_counts = {
        head: {
            value: sum(1 for r in selected if r[head] == value)
            for value in sorted({r[head] for r in selected})
        }
        for head in _HEADS
    }

    manifest = {
        "frozen_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_dir": str(source.resolve()),
        "n_rows": len(selected),
        "seed": seed,
        "sha256": _digest(selected),
        "label_counts": label_counts,
        "held_out_from": held_out_from,
        "note": (
            "Frozen evaluation set. Never train on these rows. Re-freezing "
            "invalidates every before/after comparison made against it."
        ),
    }
    (out / _MANIFEST).write_text(json.dumps(manifest, indent=2))
    return manifest


def verify(out_dir: str) -> tuple[bool, str]:
    """Check the frozen set still matches its manifest."""
    out = Path(out_dir)
    manifest_path = out / _MANIFEST
    if not manifest_path.is_file():
        return False, f"No {_MANIFEST} in {out} -- this set was never frozen."

    manifest = json.loads(manifest_path.read_text())
    rows = _read_metadata(out)
    actual = _digest(rows)
    if actual != manifest["sha256"]:
        return False, (
            "CHANGED since it was frozen.\n"
            f"  manifest: {manifest['sha256']}\n"
            f"  on disk:  {actual}\n"
            "Any before/after comparison against this set is now unsound."
        )

    missing = [
        row["filepath"]
        for row in rows
        if not (out / "volumes" / row["filepath"]).is_file()
    ]
    if missing:
        return False, f"{len(missing)} crop file(s) missing, e.g. {missing[:3]}"

    return True, (
        f"OK -- {len(rows)} rows, unchanged since {manifest['frozen_at']}."
    )


def _cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify",
        metavar="DIR",
        help="Check an already-frozen set instead of creating one",
    )
    parser.add_argument("--source-dir", help="build_dataset-shaped directory to draw from")
    parser.add_argument("--out-dir", help="Where to write the frozen set")
    parser.add_argument("--n", type=int, default=150, help="Rows to hold out (default: 150)")
    parser.add_argument("--seed", type=int, default=42, help="Sampling seed")
    parser.add_argument(
        "--split-seed",
        type=int,
        default=None,
        help="Draw only from the validation patients of this train/val split. "
        "Pass the seed the deployed model was trained with (42). Without it, "
        "most rows are data the model already fit and before/after numbers "
        "measure memorisation.",
    )
    parser.add_argument("--val-split", type=float, default=0.2)
    args = parser.parse_args()

    if args.verify:
        ok, message = verify(args.verify)
        print(message)
        sys.exit(0 if ok else 1)

    if args.split_seed is None:
        print(
            "WARNING: no --split-seed. The held-out set may include rows the "
            "model was trained on, which makes a before/after comparison "
            "meaningless. Pass --split-seed 42 for the shipped checkpoint.\n"
        )

    if not args.source_dir or not args.out_dir:
        parser.error("--source-dir and --out-dir are required unless --verify is used")

    manifest = freeze_holdout(
        args.source_dir,
        args.out_dir,
        n=args.n,
        seed=args.seed,
        split_seed=args.split_seed,
        val_split=args.val_split,
    )
    print(f"Froze {manifest['n_rows']} rows -> {args.out_dir}")
    print(f"  sha256: {manifest['sha256']}")
    if manifest["held_out_from"]:
        held = manifest["held_out_from"]
        print(
            f"  drawn from {held['candidate_rows']} rows across "
            f"{held['val_patients']} seed-{held['split_seed']} validation patients"
        )
    for head, counts in manifest["label_counts"].items():
        print(f"  {head}: {counts}")
    print("\nNever train on this set. Pass it as --holdout-dir to retrain_head.")


if __name__ == "__main__":
    _cli()
