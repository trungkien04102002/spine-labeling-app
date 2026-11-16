from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, sourced from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    inference_mode: str = "local"  # "local" | "vast"
    vast_url: str = ""
    mysql_dsn: str = "sqlite:///./spine.db"
    data_dir: str = "./data"

    # Built frontend (Vite `dist/`) served from this app so a remote user needs
    # a single URL. Empty -> use ../frontend/dist if present, else serve no UI
    # (local dev with the Vite server, and the test suite).
    frontend_dist: str = ""

    # Glob on study id for the sample studies a clinician may copy into their
    # room (graded validation cases from patients the model never trained on).
    sample_studies: str = "VAL-*,SAMPLE-*"

    # External Google Form URL used instead of the in-app questionnaire (see
    # tools/google_form/). A literal ROOM_NAME in the URL is replaced with the
    # clinician's room name. Empty means the in-app form.
    survey_form_url: str = ""

    # Read-only deployment: the UI hides editing controls and the server
    # refuses every write without the admin passphrase, so the operator can
    # still manage rooms but a stray click cannot start a long CPU grading.
    view_only: bool = False

    # Passphrase for the operator pages (/admin). Empty means no lock (local
    # development and tests); set it on any publicly reachable deployment.
    admin_password: str = ""

    # Extra browser origins allowed to call the API (comma-separated). The Vite
    # dev server is always allowed.
    cors_origins: str = ""

    # TotalSpineSeg is run out-of-process via its own CLI (it pins numpy<2 and
    # pulls in nnU-Net/torchio, which conflict with this backend's deps).
    totalspineseg_bin: str = "totalspineseg"  # CLI name or absolute path
    totalspineseg_data: str = ""  # weights dir; "" -> CLI's packaged default
    seg_device: str = "cpu"  # "cpu" | "cuda" (CLI does not accept "mps")
    # nnU-Net defaults to one worker per core, which exceeds the process/thread
    # limit of constrained containers ("libgomp: Thread creation failed"). Keep low.
    seg_max_workers: int = 1
    seg_max_workers_nnunet: int = 1
    # Device for SpineNet and the CBAM model: "auto" = GPU when available, else CPU.
    grading_device: str = "auto"

    # Directory of preprocessed RSNA discs replayed alongside corrections during
    # re-training, so a few dozen corrections cannot drag the heads away from the
    # original distribution. Not shipped with the app, so there is no default;
    # empty blocks re-training rather than silently running without replay.
    retrain_replay_dir: str = ""


def get_settings() -> Settings:
    """FastAPI dependency yielding app settings (overridable in tests)."""
    return Settings()
