from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, sourced from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    inference_mode: str = "local"  # "local" | "vast"
    vast_url: str = ""
    mysql_dsn: str = "mysql+pymysql://root@localhost:3306/spine_labeling"
    data_dir: str = "./data"

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


def get_settings() -> Settings:
    """FastAPI dependency yielding app settings (overridable in tests)."""
    return Settings()
