# Deploy on a Vast.ai GPU box

> **Do not follow this file by hand.** `tools/deploy_box.sh <PORT> <HOST>`
> does every step below in one command and verifies the result. This file
> exists to explain *why* each step is there, and to be read when the script
> reports something unexpected. Serving the app to other people is the one
> part the script does not do — that is §8.

Backend + models on the GPU VM. The frontend can either run on the laptop
behind an SSH tunnel (one user, §5) or be served by the backend itself on a
public port (anyone with the URL, §8).

## Which box to rent

Measured 2026-09-22, same studies, same code, 2–3 runs each (±2 s):

| | RTX 4090 `$0.434/h` | RTX 3060 `$0.076/h` |
|---|---|---|
| Segmentation only | 72.2 s | 107.4 s (**1.49x**) |
| Full 11-label grading | **77.5 s** | **195.8 s** (**2.53x**) |
| Output | 63 rows, 11 labels | identical |
| 72 hours | $31.2 | **$5.5** |

A 3060 is enough: peak GPU memory is **1453 MiB**, so 12 GB is eight times
what the job needs, and paying 5.7x more buys 118 seconds per study. Note the
grading models lean on the GPU harder than the segmentation does (2.53x vs
1.49x) — the opposite of what the near-zero `nvidia-smi` utilisation suggests.
Sampling every 0.5 s simply misses the bursts; removing the GPU entirely makes
a run **more than ten times** slower, so it is not optional.

Pick by, in order: **disk >= 1 GB/s**, then effective CPU cores, then the card.
A listing reading `9.0/72 CPU` gives you 9 cores. Ampere or newer; Pascal cards
(1080, 1080 Ti, P100) are cheap but current torch has been dropping their
kernels. CUDA version no longer matters when choosing — §3 handles it.

Placeholders: `<HOST>` and `<PORT>` are the Vast SSH host/port from the
instance's "Connect" panel.

> Read **§0 first**. A fresh box needs four weight stores, and three of them
> are faster to copy from the laptop than to download. Skipping that section
> is what turned a 20-minute deploy into a two-hour one on 2026-09-20.

**Measured end to end on 2026-09-21** (RTX 4090, Vast PyTorch image), following
this file step by step:

| Step | Time |
|---|---|
| §1 code onto the box (`rsync`) | 55 s |
| §2 weights + §6b held-out set (~1.4 GB) | 65 s |
| §3 `vast_setup.sh --skip-download` | **10.6 min** |
| §4 supervisor + first health check | ~30 s |
| §6b two studies and their database rows | 2 s |
| **Total to a box that grades a real study** | **~13 min** |

A full grading on that box then took **86 s** (TotalSpineSeg on CUDA 48 s,
SpineNet on CPU 38 s), against about ten minutes on a laptop CPU.

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

No credentials needed (public repo) — **but a clone gives you what is pushed,
not what is on the laptop.** On 2026-09-21 that was a month-old `main`: the
clone came back without the model-approval screen, the operator page, or the
mask-editing work, all of which existed only in unpushed local commits. Check
`git log --oneline -1` on both sides before trusting a clone, and use `rsync`
when they differ:

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
  "mkdir -p /workspace/spine-labeling-app/tss-venv/lib/python3.12/site-packages/totalspineseg/models/nnUNet &&
   tar xzf - -C /workspace/spine-labeling-app/tss-venv/lib/python3.12/site-packages/totalspineseg/models/nnUNet"
```

macOS `tar` writes `._*` AppleDouble files into the archive. Harmless, but
clean them so they never look like real checkpoints:
`ssh … 'find /workspace -name "._*" -delete'`.

Verify: `md5sum $APP/backend/models/weights/phase2_cbam.pth` →
`50101203903b1aa3bcf3d6103daa650e`, and `ls $APP/backend/spinenet/weights/*/*.pt`
→ four files.

## 2b. One line before any install: give pip a timeout

pip has **no default network timeout**. When PyPI drops a connection mid-fetch,
pip waits forever: 0% CPU, no error, the venv frozen at 13 MB, looking exactly
like a slow install. It cost 25 minutes on 2026-09-22 before the symptom was
recognised (`/proc/<pid>/wchan` reads `do_poll`, and a socket sits in
`CLOSE-WAIT`).

```bash
ssh -p <PORT> root@<HOST> 'printf "[global]\ntimeout = 30\nretries = 10\n" > /etc/pip.conf'
```

With that in place the same deploy ran start to finish in **10 min 23 s**.

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
TOTALSPINESEG_BIN=/workspace/spine-labeling-app/tss-venv/bin/totalspineseg
SEG_DEVICE=cuda
EOF

cat > /etc/supervisor/conf.d/spine_backend.conf <<'EOF'
[program:spine_backend]
command=/workspace/spine-labeling-app/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
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

**The interpreter path depends on which §3 you took.** `vast_setup.sh` builds
its own `backend/.venv`, which is what the command above uses. If you installed
by hand into `/venv/main`, use `/venv/main/bin/uvicorn` instead. Getting this
wrong shows up as `FATAL can't find command …` in `supervisorctl status`, with
no log file written at all — which reads like the service never existed.

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

## 8. Serving it to other people

§5 puts the frontend on the laptop behind an SSH tunnel. That works for one
person sitting at that laptop and for nobody else. To hand a URL to a doctor,
the box has to serve both halves itself on a port that is open to the internet.

Three steps, ~2 minutes. They are not in `deploy_box.sh`.

**1 — take a port.** Vast fixes the set of open ports when the instance is
created and will not add more later, so take one rather than ask for one. The
*self-mapped* port is the same number inside and outside the container and
bypasses Caddy, which is what lets the app answer without Vast's token — what a
link handed to someone else needs. Syncthing ships with the image and squats on
it:

```bash
ssh -p <PORT> root@<HOST>
  echo $VAST_TCP_PORT_72299          # this is the public port number
  supervisorctl stop syncthing
  # remove the Syncthing block from /etc/portal.yaml, or supervisor restores it
```

**2 — build the frontend against the public address and ship it.** The API base
is baked in at build time, so the build belongs to this box:

```bash
cd frontend && VITE_API_URL="http://<HOST>:<PUBPORT>" npx vite build
rsync -az --delete -e "ssh -p <PORT>" dist/ root@<HOST>:/workspace/spine-labeling-app/frontend/dist/
```

**3 — rebind the backend to that port and let it serve the UI.** One process
serves both, so there is no CORS to configure and no second port to explain.
Binding `0.0.0.0` is what actually exposes it; `127.0.0.1` stays invisible
however open the port is. In `/etc/supervisor/conf.d/spine_backend.conf`:

```ini
command=<repo>/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port <PUBPORT>
environment=TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD="1",FRONTEND_DIST="<repo>/frontend/dist"
```

then `supervisorctl reread && supervisorctl update && supervisorctl restart spine_backend`.

### Verify from the laptop, not from the box

Curling `localhost` on the box passes even when nothing outside can reach it,
which is the failure this whole section exists to avoid. All six must answer:

```bash
U=http://<HOST>:<PUBPORT>
curl -s -o /dev/null -w '%{http_code}\n' $U/                       # 200, text/html
curl -s $U/health                                                   # {"status":"ok"}
curl -s $U/patients | python3 -c 'import json,sys; print(sum(len(p["studies"]) for p in json.load(sys.stdin)))'
curl -s -o /dev/null -w '%{http_code}\n' $U/viewer/DEMO-001        # 200 -- SPA fallback
curl -s -o /dev/null -w '%{http_code}\n' $U/assets/index-*.css     # 200
curl -s -o /dev/null -w '%{http_code} %{size_download}\n' $U/studies/DEMO-001/display.nii.gz
```

The last one matters most: ~4 MB means another machine opening the viewer sees
a real image rather than a black frame.

### A stable address instead of an IP and a port

`http://IP:PORT` dies with the instance and is plain HTTP. For a trial where
people bookmark the link, put a Cloudflare named tunnel in front:

```bash
/opt/instance-tools/bin/cloudflared tunnel run --token <TOKEN>   # under supervisor, autorestart=true
```

The token belongs to the **Cloudflare account, not the machine**: run it on a
brand-new box and the same hostname keeps working, so the box can be replaced
mid-trial without anyone's bookmark breaking. Do not run two boxes on one token
— Cloudflare load-balances between them and half the requests reach the dead
one. Needs a domain on Cloudflare DNS (a `.xyz` is about a dollar for the first
year); nameserver changes can take up to 24 hours, so buy it before the day you
need it, not on it.

The no-domain fallback, `cloudflared tunnel --url http://localhost:<PUBPORT>`,
issues a **new random hostname on every restart** and caps at 200 concurrent
requests. Fine for a quick look, not for a link anyone saves.

---

## 9. During the trial: rooms, the operator page, and getting the data out

**Rooms.** A clinician makes a room once (name + a 4-digit PIN typed twice)
and gets their own studies, corrections, correction queue and survey answers.
After that the door lists every name: tap yours, type your PIN. Forgot the
PIN? Send their personal link from `/admin` (a link skips the PIN), or press
"Reset PIN" there and they choose a new one on next entry. Rooms made from
`/admin`, or before PINs existed, ask for a PIN on first entry. It is
separation, not security -- the PIN stops a tap on the wrong name, nothing more.
An empty room offers the graded `VAL-*` cases to copy in (`SAMPLE_STUDIES` in
`backend/.env` changes the pattern); each copy is the model's original output,
none of the corrections made to the sample since.

**The operator page** is `/admin`, behind `ADMIN_PASSWORD`. It holds the room
list, survey results with every response readable on its own, feedback and
re-training, model versions, and the export. No clinician page links to it.
`vast_setup.sh` rewrites `backend/.env`, so the passphrase is carried over by
`deploy_box.sh` from the laptop's `backend/.env` -- **its verification must
print `admin lock : {"locked":true}`**, or clinicians can open everything.

**Where the data is on the box**, and both go when the instance is destroyed:

```
/workspace/spine-labeling-app/backend/spine.db     rooms, survey answers, corrections
/workspace/spine-labeling-app/backend/data/<id>/   uploaded scans, masks, grades
```

**Getting it out -- before destroying the box:**

1. `/admin` → *Xuất dữ liệu* → **Download everything (.zip)**. One file to the
   laptop through the browser, no SSH: `readers.csv`, `survey_responses.csv`,
   `questions.csv`, `corrections.csv` and a consistent `spine.db` snapshot. The
   CSVs carry a UTF-8 byte-order mark so Excel shows Vietnamese correctly.
2. The scans clinicians uploaded are **not** in the zip (hundreds of MB). If
   they are needed:

   ```bash
   rsync -az -e "ssh -p <PORT>" \
     root@<HOST>:/workspace/spine-labeling-app/backend/data/ \
     ~/trial-data-$(date +%Y%m%d)/
   ```

**Reading `corrections.csv`:** `before` is the model's value only on the first
edit to a cell; a second edit's `before` is the first edit's `after`. For
agreement with the model, take the earliest row per `(room, study, level,
condition)`.

**Never renumber survey questions once anyone has answered.** Answers are
stored by question id; renumbering silently moves every answer onto a different
question. `tests/test_survey.py::test_question_ids_keep_their_meaning` pins the
ids -- if it fails, the fix is a new id, not an edited test.

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
| `supervisorctl status` says `FATAL can't find command .../uvicorn`, no log file | the supervisor command names the wrong venv for the §3 path you took (§4). |
| A fresh clone is missing screens that exist on the laptop | `main` is not pushed; rsync instead (§1). |
| `/admin` blocked: "No replay set is configured" | expected on a box without the 8.2 GB replay set (§6b). Copy it, or run without replay deliberately. |
| `/retraining/readiness` answers 500 | a backend older than 2026-09-21 with no `data/holdout_frozen`. Copy the held-out set (§6b); newer builds report it as a blocker instead. |
| Everything works but each grading takes minutes longer than the table above | torch is on the CPU. `requirements.txt` pins no torch, so pip serves whichever CUDA build is current (cu130); a driver capped at 12.6 imports it happily and reports no GPU, and **nothing errors**. §3 now refetches a matching build; check `torch GPU` in the script's verification. |
| `RuntimeError: operator torchvision::nms does not exist`, ~73 s into a grading run | torch was replaced but torchvision was not: pip leaves it alone because its version still satisfies the requirement, while its compiled ops link against the torch that went. Reinstall it from the **same** index with `--force-reinstall --no-deps`. Note `torch.cuda.is_available()` answers `True` over this — the check has to import torchvision and touch a compiled op. |
| `pip install` sits at 0% CPU, venv frozen, no error | pip has no default network timeout and is waiting on a dropped PyPI connection forever. `/proc/<pid>/wchan` reads `do_poll`. See §2b; set `/etc/pip.conf` before deploying. |
| A study opens with the previous patient's mask and grades | fixed 2026-09-22: re-upload used to replace only the series rows. On an older build, delete the study and re-create it. |
| Google Drive download quota | Drive counts per **account**, not per file; re-uploading does not lift it. `scp` instead. |
