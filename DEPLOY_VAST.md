# Deploy on a Vast.ai GPU box

Backend + models on the GPU VM, frontend on the laptop, SSH tunnel between
them. GPU cuts a full grading run from ~10 min/volume to **~84 s** (measured,
RTX 4090, 2026-09-20: TotalSpineSeg + SpineNet + CBAM end to end).

Placeholders: `<HOST>` and `<PORT>` are the Vast SSH host/port from the
instance's "Connect" panel.

> Read **§0 first**. A fresh box needs four weight stores, and three of them
> are faster to copy from the laptop than to download. Skipping that section
> is what turned a 20-minute deploy into a two-hour one on 2026-09-20.

---

## 0. The weight stores — copy, don't download

`.gitignore` excludes every weight file, so a fresh clone has **none** of
these. All four are needed before a single grading run will complete.

| # | Path (on the VM, under `backend/`) | Size | Where to get it |
|---|---|---|---|
| 1 | `models/weights/phase2_cbam.pth` | 243 MB | laptop (md5 `50101203903b1aa3bcf3d6103daa650e`) |
| 2 | `spinenet/weights/{appearance,context}/*.pt` | 9 MB | laptop |
| 3 | `spinenet/weights/detect-vfr/ckpt435.pt` | 433 MB | laptop, else robots.ox.ac.uk |
| 4 | `spinenet/weights/grading/ckpt1.pt` | 243 MB | laptop, else robots.ox.ac.uk |
| 5 | TotalSpineSeg nnUNet models (own venv) | 274 MB | laptop |

**Copy from the laptop first, always.** Measured on 2026-09-20: `scp` of the
243 MB checkpoint took **12 s** (29 MB/s); the same file from
robots.ox.ac.uk took minutes and stalled, and `totalspineseg_init` failed its
weight download five times in a row (`ContentTooShortError`, then
`BadZipFile`). Search the disk before reaching for a URL — copies of these
files exist in `~/spinet-v2/spinenet/weights/` and `~/SpineNet/` too.

**These files go missing.** The `.pth` cleanup of 2026-08-04 deleted
`detect-vfr/ckpt435.pt`, `grading/ckpt1.pt` and the TotalSpineSeg
`Dataset101_step1` checkpoint from the laptop. The app kept starting and the
UI kept loading; only a full grading run failed, three stages in. Check the
dirs are non-empty before assuming the laptop is a good source:

```bash
find ~/spine-labeling-app/backend/spinenet/weights -name '*.pt' | wc -l   # want 4
find ~/totalspineseg/totalspineseg/models -name 'checkpoint_*.pth' | wc -l # want 2
```

The DB is created on startup, and `backend/data/` is excluded, so the VM
starts with an empty worklist.

---

## 1. Code onto the VM

```bash
ssh -p <PORT> root@<HOST> 'cd /workspace &&
  git clone https://github.com/trungkien04102002/spine-labeling-app.git'
```

No credentials needed (public repo). `rsync` also works if GitHub is out:

```bash
rsync -az -e "ssh -p <PORT>" \
  --exclude node_modules --exclude .venv --exclude backend/data \
  --exclude __pycache__ --exclude '*.pth' --exclude '*.db' \
  ~/spine-labeling-app/ root@<HOST>:/workspace/spine-labeling-app/
```

macOS ships rsync 2.6.9, which has no `--info=progress2`. For big directories
prefer `tar | ssh 'tar x'`, which is also what the weight copies below use.

## 2. Weights onto the VM (laptop, ~1 min total)

```bash
APP=/workspace/spine-labeling-app

# 1 + 2/3/4 -- grading checkpoint and the whole vendored SpineNet weight tree
scp -P <PORT> ~/spine-labeling-app/backend/models/weights/phase2_cbam.pth \
  root@<HOST>:$APP/backend/models/weights/
cd ~/spine-labeling-app/backend/spinenet &&
  tar czf - weights | ssh -p <PORT> root@<HOST> "tar xzf - -C $APP/backend/spinenet"

# 5 -- TotalSpineSeg nnUNet models into the venv the CLI will run from
cd ~/totalspineseg/totalspineseg/models/nnUNet &&
  tar czf - results | ssh -p <PORT> root@<HOST> \
  "mkdir -p /workspace/tss-venv/lib/python3.12/site-packages/totalspineseg/models/nnUNet &&
   tar xzf - -C /workspace/tss-venv/lib/python3.12/site-packages/totalspineseg/models/nnUNet"
```

macOS `tar` writes `._*` AppleDouble files into the archive. Harmless, but
clean them so they never look like real checkpoints:
`ssh … 'find /workspace -name "._*" -delete'`.

Verify: `md5sum $APP/backend/models/weights/phase2_cbam.pth` →
`50101203903b1aa3bcf3d6103daa650e`, and `ls $APP/backend/spinenet/weights/*/*.pt`
→ four files.

## 3. Python on the VM — run `vast_setup.sh` first

```bash
cd /workspace/spine-labeling-app && ./vast_setup.sh --skip-download
```

It installs the backend deps, writes `backend/.env` (SQLite + CUDA
segmentation), and builds `tss-venv` with the versions already pinned:
`totalspineseg==20250416 nnunetv2==2.4.2 torch==2.4.1`. It is re-runnable, one
failing step does not abort the rest, and it prints a summary of what is OK or
missing. `--skip-download` because §2 already placed the checkpoint by hand;
without it the script pulls from Drive, whose quota is per **account**, so a
re-upload does not lift it.

**Use the script.** The 2026-09-20 deploy installed everything by hand instead
and rediscovered, the slow way, two things the script had already solved --
`pip install totalspineseg` unpinned ships without nnunetv2
(`ModuleNotFoundError: No module named 'nnunetv2'`), and torch >=2.6 flipped
`torch.load(weights_only=True)`, which stops nnunetv2 2.4.2 loading its own
checkpoints (`UnpicklingError: Weights only load failed`). Both are pinned
away at `vast_setup.sh:111`, comment included.

What the script does **not** do: the SpineNet weight stores in §0. It handles
`phase2_cbam.pth` only, so grading still dies at the SpineNet stage until
`backend/spinenet/weights/` is populated.

### If you install by hand anyway

Reuse `/venv/main` -- the Vast PyTorch image already ships torch with CUDA
(2.14.0+cu130 on 2026-09-20), so a fresh venv re-downloads ~2.5 GB for nothing:

```bash
source /venv/main/bin/activate
cd /workspace/spine-labeling-app/backend && uv pip install -r requirements.txt
```

TotalSpineSeg needs **its own** venv (it pins numpy<2). If its torch ends up
>=2.6 rather than the pinned 2.4.1, the weights_only flip above applies and
`TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1` in the backend's environment is the way
out (§4) -- the backend passes its env straight to the CLI. That is what the
box currently runs on.

Pinning also keeps the segmentation label ids stable. `app/inference/crops.py`
maps TotalSpineSeg disc labels 92/93/94/95/100 to the five lumbar levels; a
newer release that renumbered them would move every crop without raising a
single error.

## 4. Run the backend as a supervisor service

Not a bare `uvicorn &` — that dies with the SSH session. Supervisor also
restarts it after a crash and keeps the log in one place.

```bash
cat > /workspace/spine-labeling-app/backend/.env <<'EOF'
MYSQL_DSN=sqlite:///./spine.db
TOTALSPINESEG_BIN=/workspace/tss-venv/bin/totalspineseg
SEG_DEVICE=cuda
EOF

cat > /etc/supervisor/conf.d/spine_backend.conf <<'EOF'
[program:spine_backend]
command=/venv/main/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
directory=/workspace/spine-labeling-app/backend
; nnunetv2 2.4.2 predates torch 2.6, where torch.load flipped weights_only to
; True by default. Without this the TotalSpineSeg subprocess cannot load its
; own checkpoints (UnpicklingError: Weights only load failed). The backend
; passes its environment straight through to the CLI.
environment=TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD="1"
autostart=true
autorestart=true
stdout_logfile=/var/log/spine_backend.log
redirect_stderr=true
stopasgroup=true
killasgroup=true
EOF

supervisorctl reread && supervisorctl update
supervisorctl status spine_backend && curl -s localhost:8000/health
```

`supervisorctl restart spine_backend` after changing `.env`; the log is
`/var/log/spine_backend.log`.

## 5. Tunnel and frontend (laptop)

The instance's external ports are allocated at creation and were all taken by
Jupyter/Syncthing/Tensorboard, so nothing is exposed publicly — the tunnel is
the only way in, which is also what keeps patient data off the internet.

```bash
# backgrounded; survives closing the shell, dies with the laptop
ssh -fN -p <PORT> -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -L 8000:localhost:8000 root@<HOST>

cd ~/spine-labeling-app && ./run.sh frontend     # :5173, VITE_API_URL defaults to :8000
```

Node is **not** needed on the VM — the frontend stays on the laptop, so Vite
hot-reload is instant. (If you ever do run it there: nvm only lands on `PATH`
in an interactive login shell; `. /opt/nvm/nvm.sh` first.)

Check the tunnel with `curl -s localhost:8000/health`. A blank page in the
browser with the box still healthy almost always means the tunnel dropped —
re-run the `ssh -fN` line.

To run the local backend alongside the tunnel (e.g. to test the demo path),
give it another port: `PORT=8001 ./run.sh backend`.

## 6. First use

Worklist starts empty. Either upload through the UI, or load the eight-case
validation set (see `tools/` and `docs/validation/COMPARISON.md`):

```bash
cd ~/spine-labeling-app
python3 tools/build_validation_set.py --api http://localhost:8000
python3 tools/compare_validation_set.py
```

## 6b. What `/admin` and re-training need on a box

The operator page checks three things before it will let a run start, and a box
that has only the code has none of them. `data/` is gitignored, so like the
weight stores in §0 it does not travel.

| What | Where | Without it |
|---|---|---|
| Frozen held-out set | `backend/data/holdout_frozen` (173 MB) | `/admin` reports it as a blocker; no run can start |
| Replay set | a copy of `rsna_preprocessed` (**8.2 GB**, from the research repo) | the run is blocked, with a replay-free run behind its own labelled button |
| `RETRAIN_REPLAY_DIR` | `backend/.env` | as above — the setting is empty by default |

```bash
# held-out set, from the laptop (seconds)
cd ~/spine-labeling-app/backend && tar czf - data/holdout_frozen \
  | ssh -p <PORT> root@<HOST> \
    'cd /workspace/spine-labeling-app/backend && tar xzf -'

# replay set, only if the box should actually re-train (~5 min at 29 MB/s)
cd ~/spinet-v2 && tar czf - rsna_preprocessed \
  | ssh -p <PORT> root@<HOST> 'cd /workspace && tar xzf -'
# then in backend/.env on the box:
#   RETRAIN_REPLAY_DIR=/workspace/rsna_preprocessed
```

Leaving the replay set off is a legitimate deployment: `/admin` then shows the
trigger blocked and says which setting is missing and why it matters, which is
the honest state rather than a broken one. Skipping the **held-out** set is not
— nothing can be evaluated without it, so copy that one always.

Check it landed: `curl -s localhost:8000/retraining/readiness` should report
`holdout_present: true` with a message like `"OK -- 200 rows, unchanged since
2026-07-26"`. That string is the checksum verifying the set is the one that was
frozen; if it says anything else, the set is not the one past numbers were
measured against.

On 2026-09-20 this section did not exist, the box was deployed without either
directory, and `/retraining/readiness` answered **500** rather than naming what
was missing — the page whose job is to report gaps was the first thing to fall
over. That is fixed, but the copying still has to happen.

---

## 7. Moving graded studies between the box and the laptop

A box with no host volume loses everything when it is recycled or destroyed
(`vast-capabilities | jq '.instance.workspace_is_volume'` — `false` on the
2026-09-20 box). Grading is the expensive part, so pull finished studies down
rather than re-running them: 326 MB of eight graded studies took **13 seconds**,
against roughly 80 minutes to grade them again on a laptop CPU.

```bash
# laptop — studies + the box's database, into a staging dir
mkdir -p /tmp/boxpull
ssh -p <PORT> root@<HOST> \
  'cd /workspace/spine-labeling-app/backend && tar czf - spine.db data/VAL-*' \
  | tar xzf - -C /tmp/boxpull
cp -R /tmp/boxpull/data/VAL-* ~/spine-labeling-app/backend/data/
```

**The database stores absolute paths, so it cannot simply be copied over.**
`studies.volume_path`, `studies.display_path`, `series.volume_path`,
`series.display_path` and `annotations.mask_path` all point at
`/workspace/spine-labeling-app/backend/…`. Copy that database onto a laptop
unchanged and every study opens blank — the worklist looks right, which is what
makes it confusing.

Merging (keeping the laptop's own studies) rather than overwriting means, per
study: insert its patient and keep the new row id, insert the study against
that id, then its `series`, `annotations` and `correction_log` rows, rewriting
the prefix `/workspace/spine-labeling-app/backend/` to the local one in every
path column. Delete any rows for the same study ids first, so a second run does
not stack duplicates. Back the laptop database up before starting
(`cp spine.db spine.db.bak.$(date +%Y%m%d-%H%M%S)`).

Verify by serving it, not by trusting the copy — start the backend on a spare
port and check a study actually grades back:

```bash
PORT=8001 ./run.sh backend
curl -s localhost:8001/patients
curl -s localhost:8001/studies/<STUDY_ID>/grade_full   # expect a full grading table
```

Going the other way (seeding a fresh box with studies already graded on the
laptop) is the same in reverse, rewriting the prefix the other way.

---

---

## Symptom → cause

| Symptom | Cause |
|---|---|
| `Access denied for user 'root'@'localhost'` at startup, `/health` never answers | `.env` fell back to the MySQL DSN. Set `MYSQL_DSN=sqlite:///./spine.db`. |
| `ModuleNotFoundError: No module named 'nnunetv2'` | unpinned `totalspineseg`. Reinstall pinned (§3). |
| `UnpicklingError: Weights only load failed` | torch ≥2.6 vs nnunetv2 2.4.2. Set `TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1` (§4). |
| `NameError: save path .../detect-vfr could not be found` | store 3 missing (§0). |
| `ValueError: max() iterable argument is empty` | the `detect-vfr/` dir exists but holds no `.pt`. Same fix. |
| `FileNotFoundError: .../Dataset101_.../fold_0/checkpoint_best.pth` | store 5 missing or partially deleted. |
| Grading job stuck at 70%, GPU idle | normal. SpineNet runs on CPU (`device="cpu"` in `spinenet_grading.py`); only TotalSpineSeg uses CUDA. |
| MRI canvas black in headless Chrome | needs software WebGL: `--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader`. |
| `/admin` blocked: "No replay set is configured" | expected on a box without the 8.2 GB replay set (§6b). Copy it, or run without replay deliberately. |
| `/retraining/readiness` answers 500 | a backend older than 2026-09-21 with no `data/holdout_frozen`. Copy the held-out set (§6b); newer builds report it as a blocker instead. |
| Google Drive download quota | Drive counts per **account**, not per file; re-uploading does not lift it. `scp` instead. |
