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


def freeze_holdout(
    source_dir: str,
    out_dir: str,
    n: int = 150,
    seed: int = 42,
) -> dict:
    """Sample `n` rows, copy their crops, and write a tamper-evident manifest.

    Sampling is stratified over the label combination: `Severe` is rare enough
    that a uniform draw can miss it entirely, which would leave the evaluation
    blind to the exact class the work is about.

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
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if args.verify:
        ok, message = verify(args.verify)
        print(message)
        sys.exit(0 if ok else 1)

    if not args.source_dir or not args.out_dir:
        parser.error("--source-dir and --out-dir are required unless --verify is used")

    manifest = freeze_holdout(args.source_dir, args.out_dir, n=args.n, seed=args.seed)
    print(f"Froze {manifest['n_rows']} rows -> {args.out_dir}")
    print(f"  sha256: {manifest['sha256']}")
    for head, counts in manifest["label_counts"].items():
        print(f"  {head}: {counts}")
    print("\nNever train on this set. Pass it as --holdout-dir to retrain_head.")


if __name__ == "__main__":
    _cli()
