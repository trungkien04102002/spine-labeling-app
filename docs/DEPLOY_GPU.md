# Deploy on a GPU server

One Ubuntu machine with an NVIDIA GPU runs everything: the API, the models and
the built frontend, on a single port. Clinicians open one URL.

For rented Vast.ai machines there is a longer runbook with every trap met
during the 2026 trial, and a script that does all of this from your own
machine: [DEPLOY_VAST.md](../DEPLOY_VAST.md), `tools/deploy_box.sh`.

## What the machine needs

| | Minimum | Used in the trial |
|---|---|---|
| GPU | NVIDIA, ~2 GB memory (RTX 3060 is enough) | RTX 3090 / 4090 |
| Disk | 15 GB free | 80 GB |
| RAM | 16 GB | 32-64 GB |
| OS | Ubuntu 22.04 with the NVIDIA driver (`nvidia-smi` works) | Vast.ai PyTorch image |

Grading one scan: ~1 minute on a 4090, ~3 minutes on a 3060. Network speed
to the clinicians matters more than the GPU once it is set up: a scan's image
is 4-10 MB, so check the download speed from the server to where the users are
(a server with fast upload but 50 KB/s download towards Vietnam made every
image take a minute to open).

## Steps

```bash
# as root (sudo -i)
# 1. Node 22 for building the frontend (Ubuntu's own nodejs is too old)
curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y nodejs

# 2. code + everything else (~15 min: Python deps, weights, TotalSpineSeg)
git clone https://github.com/trungkien04102002/spine-labeling-app.git
cd spine-labeling-app
./vast_setup.sh
```

`vast_setup.sh` works on any Ubuntu GPU machine, not only Vast. It writes
`backend/.env` (SQLite, `SEG_DEVICE=cuda`), downloads the weights with
`tools/fetch_assets.py`, installs TotalSpineSeg into `tss-venv/`, makes sure
torch can see the GPU, and ends with a summary of anything that failed. It is
safe to re-run.

```bash
# 3. check it grades (uploads sample_volumes/100_t2.mha through the API)
tools/check.sh --gpu                       # expect "SMOKE OK" and "ALL CHECKS PASSED"

# 4. lock the operator page, then build the frontend for same-origin serving
echo "ADMIN_PASSWORD=<choose one>" >> backend/.env
(cd frontend && VITE_API_URL="" npm run build)   # -> frontend/dist, served by the backend

# 5. serve on all interfaces
HOST=0.0.0.0 PORT=8000 ./run.sh backend
```

Open `http://<server-ip>:8000` from another machine. The backend serves
`frontend/dist` when it exists (or the path in `FRONTEND_DIST`).
`VITE_API_URL=""` makes the pages call the API on whatever address they were
loaded from, so the same build works on an IP or a domain name.

Checking from the server with `curl` is not enough: open a study in a real
browser from outside. The images are drawn with WebGL, and several bugs met in
the trial showed a black image while every request returned 200.
`node tools/diagnose_viewer.mjs <url> <study> <room id> /tmp 3` does this
headlessly and reports the image brightness.

## Keeping it running

`run.sh` starts a background process that dies with the machine. For a server,
run the same command under a process manager. With supervisor (what the Vast
images use):

```ini
; /etc/supervisor/conf.d/spine_backend.conf
[program:spine_backend]
directory=/root/spine-labeling-app/backend
command=/root/spine-labeling-app/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
autorestart=true
stdout_logfile=/var/log/spine_backend.log
redirect_stderr=true
```

`supervisorctl reread && supervisorctl update`. The log shows every upload
(`[upload …] received …`) and every grading job (`[job grade_full …] done in
Ns` or `FAILED … at stage …`), which is the first place to look when a user
reports a problem.

## Updating a server that already has users' data

Do not re-run `deploy_box.sh` or replace `backend/spine.db`: studies,
corrections and survey answers live in `backend/spine.db` and
`backend/data/`. Pull the code, rebuild the frontend, restart:

```bash
cp backend/spine.db backend/spine.db.bak.$(date +%Y%m%d-%H%M)
git pull
backend/.venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm install && VITE_API_URL="" npm run build)
supervisorctl restart spine_backend
```

Tell users to hard-refresh (Ctrl/Cmd+Shift+R) once; an open tab keeps the old
JavaScript.

## Moving the database to another machine

Paths in the database are absolute (`/root/spine-labeling-app/backend/data/…`).
Either install at the same path on the new machine, or rewrite the prefix in
every path column after copying (DEPLOY_VAST.md §7 lists the columns). To move just one graded study, use
`tools/demo_case.py export` / `import`, which stores paths relative to the
study.
