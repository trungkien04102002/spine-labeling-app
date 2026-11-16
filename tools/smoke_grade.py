"""End-to-end check against a running backend: upload a volume, grade it.

    backend/.venv/bin/python tools/smoke_grade.py [--api http://127.0.0.1:8000]
                                                  [--volume sample_volumes/100_t2.mha]

Does what a clinician does in the UI, through the same API: open a room,
create a study, upload a SPIDER volume, start grading, poll until it finishes,
then check the result holds the 11 conditions on the lumbar discs. Exits
non-zero on any failure. Needs the weights and TotalSpineSeg installed; on a
GPU it takes about a minute, on a laptop CPU 10+ minutes.

It leaves the room "__smoke" and its study behind, so the result can be opened
in the UI afterwards (worklist -> room "__smoke").
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]
CONDITIONS = 11  # 3 from model A + 8 from upstream SpineNet


def fail(msg: str) -> None:
    sys.exit(f"SMOKE FAIL: {msg}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://127.0.0.1:8000")
    p.add_argument("--volume", type=Path, default=REPO / "sample_volumes/100_t2.mha")
    p.add_argument("--timeout", type=int, default=1800, help="seconds")
    a = p.parse_args()
    if not a.volume.is_file():
        fail(f"{a.volume} missing; run: python3 tools/fetch_assets.py demo")

    s = requests.Session()
    r = s.post(f"{a.api}/readers", json={"name": "__smoke"})
    r.raise_for_status()
    s.headers["X-Reader-Id"] = str(r.json()["id"])

    sid = f"smoke-{int(time.time())}"
    r = s.post(f"{a.api}/studies", json={"id": sid, "patient_name": "smoke test"})
    r.raise_for_status()
    sid = r.json()["id"]  # room-prefixed

    with a.volume.open("rb") as f:
        r = s.post(f"{a.api}/studies/{sid}/upload", files={"file": (a.volume.name, f)})
    if r.status_code != 200:
        fail(f"upload HTTP {r.status_code}: {r.text[:300]}")
    print(f"uploaded {a.volume.name} as {sid}")

    r = s.post(f"{a.api}/studies/{sid}/grade_full/start")
    if r.status_code != 202:
        fail(f"start grading HTTP {r.status_code}: {r.text[:300]}")
    job = r.json()["id"]
    t0 = time.time()
    while True:
        j = s.get(f"{a.api}/jobs/{job}").json()
        print(f"\r  {j['status']:7} {j.get('stage') or '':40} {time.time() - t0:5.0f} s", end="")
        if j["status"] == "done":
            break
        if j["status"] == "error":
            print()
            fail(f"grading error: {j.get('error')}")
        if time.time() - t0 > a.timeout:
            print()
            fail(f"grading still running after {a.timeout} s")
        time.sleep(3)
    print()

    res = s.get(f"{a.api}/studies/{sid}/grade_full").json()
    items = res["grading"]
    levels = sorted({i["level"] for i in items})
    conditions = {i["condition"] for i in items}
    if len(conditions) != CONDITIONS:
        fail(f"expected {CONDITIONS} conditions, got {sorted(conditions)}")
    if not levels:
        fail("no disc levels graded")
    if not res.get("segmentation"):
        fail("no segmentation mask in the result")
    print(f"SMOKE OK: {len(items)} grades, levels {', '.join(levels)}, "
          f"{time.time() - t0:.0f} s, model {res['model_version']}")
    print(f"open it: worklist -> room __smoke -> {sid}")


if __name__ == "__main__":
    main()
