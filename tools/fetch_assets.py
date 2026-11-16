"""Download the files git does not carry: model weights and sample cases.

    python3 tools/fetch_assets.py            # everything (~1.1 GB)
    python3 tools/fetch_assets.py demo       # only the sample cases (~40 MB)
    python3 tools/fetch_assets.py models     # only the weights

They live on the GitHub Release ASSETS_TAG of this repo. Each file is checked
against its md5, so a cut-off download is caught here and not three stages
into a grading run. Re-running skips files that are already in place.

Not handled here: TotalSpineSeg fetches its own weights with
`totalspineseg_init` (see README), and the optional model B is built with
tools/build_reference_b.py.

Standard library only, so it runs before any virtualenv exists.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BASE_URL = (
    "https://github.com/trungkien04102002/spine-labeling-app"
    "/releases/download/assets-v1"
)

# name -> (group, md5, (how, target, file whose presence means "done"))
ASSETS = {
    # Model A: the 3D ResNet34 + CBAM grading model trained in spinet-v2
    # (checkpoints/rsna/best_model_attention.pth, renamed).
    "phase2_cbam.pth": (
        "models",
        "50101203903b1aa3bcf3d6103daa650e",
        ("copy", "backend/models/weights/phase2_cbam.pth", None),
    ),
    # Upstream SpineNet (Oxford VGG): detection, labelling and the 8 grades
    # model A does not produce. Same files spinenet.download_weights() fetches
    # from robots.ox.ac.uk, which is slow and has failed mid-transfer.
    "spinenet_weights.tar": (
        "models",
        "c77ad34fb508c2c1c40b61227e72d238",
        ("untar", "backend/spinenet", "weights/detect-vfr/ckpt435.pt"),
    ),
    # Three SPIDER T2 sagittal volumes (CC BY 4.0) to upload and grade.
    "sample_volumes.zip": (
        "demo",
        "62fac7173cf1fff59c80886d15a2216f",
        ("unzip", "sample_volumes", "107_t2.mha"),
    ),
    # SPIDER case 100, already graded; tools/demo_case.py imports it.
    "demo_case.zip": (
        "demo",
        "085b48736335344f7380ab19ea178936",
        ("copy", "sample_volumes/demo_case.zip", None),
    ),
}


def md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(name: str, dest: Path) -> None:
    url = f"{BASE_URL}/{name}"
    print(f"  downloading {url}")
    try:
        resp = urllib.request.urlopen(url)
    except urllib.error.URLError as e:
        hint = ""
        if "CERTIFICATE_VERIFY_FAILED" in str(e):
            hint = (
                "\n  Behind a TLS-inspecting proxy? Point SSL_CERT_FILE at a CA"
                " bundle that includes the proxy's root certificate."
            )
        sys.exit(f"FAIL {name}: {e}{hint}")
    with resp, dest.open("wb") as out:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done / 1e6:7.1f} / {total / 1e6:.1f} MB", end="")
        print()


def install(name: str, want_md5: str, how: tuple) -> None:
    kind, target, sentinel = how
    target_path = REPO / target
    already = (
        (target_path / sentinel).is_file()
        if sentinel
        else target_path.is_file() and md5(target_path) == want_md5
    )
    if already:
        print(f"ok   {name} (already in place)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / name
        download(name, f)
        got = md5(f)
        if got != want_md5:
            sys.exit(f"FAIL {name}: md5 {got}, expected {want_md5}. Re-run.")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "copy":
            shutil.move(str(f), target_path)
        elif kind == "untar":
            with tarfile.open(f) as t:
                t.extractall(target_path)
        elif kind == "unzip":
            with zipfile.ZipFile(f) as z:
                z.extractall(target_path)
    print(f"ok   {name} -> {target}")


def main() -> None:
    group = sys.argv[1] if len(sys.argv) > 1 else "all"
    if group not in {"all", "demo", "models"}:
        sys.exit(__doc__)
    for name, (g, want, how) in ASSETS.items():
        if group in ("all", g):
            install(name, want, how)


if __name__ == "__main__":
    main()
