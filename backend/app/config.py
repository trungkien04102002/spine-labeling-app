from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, sourced from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    inference_mode: str = "local"  # "local" | "vast"
    vast_url: str = ""
    mysql_dsn: str = "mysql+pymysql://root@localhost:3306/spine_labeling"
    data_dir: str = "./data"

    # Built frontend (Vite `dist/`) to serve from this same app. Serving both
    # from one port is what lets a remote user open a single URL; the split
    # localhost:5173 + localhost:8000 setup only works on the developer's own
    # machine. Empty -> look for ../frontend/dist, and if that is absent serve
    # no UI at all, which is what local dev and the test suite expect.
    frontend_dist: str = ""

    # Studies a clinician may copy into their room to try the tool, as a glob
    # on the study id. The RSNA validation cases: already graded, with ground
    # truth, from patients the model never trained on.
    sample_studies: str = "VAL-*"

    # The questionnaire as a Google Form instead of the in-app one: its link
    # (tools/google_form/ makes the Form and prints it; a literal ROOM_NAME in
    # the link is replaced with the clinician's room name). Answers then
    # live in the Form's Sheet, safe from a box being destroyed. Empty means
    # the in-app form.
    survey_form_url: str = ""

    # A box clinicians only look at: every study already graded, nothing to
    # correct (there is no retraining loop to feed). The pages hide every
    # editing control, and the server refuses every write that does not carry
    # the admin passphrase -- so the operator can still set rooms up, and a
    # stray click cannot start a 30-minute CPU grading on a small server.
    view_only: bool = False

    # Passphrase for the operator pages (/admin): who is in which room, the
    # survey results, exports, switching models, re-training. Empty means no
    # lock, which is what local development and the test suite use; set it on
    # any box a clinician can reach.
    admin_password: str = ""

    # Browser origins allowed to call the API (comma-separated). The Vite dev
    # server is always allowed; add more when the frontend runs on another host
    # (e.g. laptop UI hitting a backend exposed directly, without an SSH tunnel).
    cors_origins: str = ""

    # TotalSpineSeg is run out-of-process via its own CLI (it pins numpy<2 and
    # pulls in nnU-Net/torchio, which conflict with this backend's deps).
    totalspineseg_bin: str = "totalspineseg"  # CLI name or absolute path
    totalspineseg_data: str = ""  # weights dir; "" -> CLI's packaged default
    seg_device: str = "cpu"  # "cpu" | "cuda" (CLI does not accept "mps")
    # nnU-Net spawns worker processes/threads; on constrained containers (e.g.
    # Vast) the default (= all cores) hits the process/thread limit and dies
    # ("libgomp: Thread creation failed" / "Background workers died"). Cap low.
    seg_max_workers: int = 1
    seg_max_workers_nnunet: int = 1
    # SpineNet + the CBAM model: "auto" = the GPU when torch sees one, else CPU.
    # "cpu" forces the old behaviour (e.g. to compare outputs).
    grading_device: str = "auto"

    # Re-training (POST /corrections/batches/{id}/retrain) mixes ~200 ORIGINAL
    # discs into the corrections so the heads stay anchored to the distribution
    # the deployed checkpoint learned; without them a few dozen corrections pull
    # the model wherever they happen to point. Those discs are the preprocessed
    # RSNA set from the research repo (~8.2 GB), which is NOT part of this
    # application and sits at a different path on every machine -- hence a
    # setting with no default rather than a guessed path. Empty means "not
    # configured", which the operator page shows as a blocked state instead of
    # quietly running the weaker, replay-free experiment.
    retrain_replay_dir: str = ""


def get_settings() -> Settings:
    """FastAPI dependency yielding app settings (overridable in tests)."""
    return Settings()
