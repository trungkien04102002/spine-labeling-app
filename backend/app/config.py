from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, sourced from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    inference_mode: str = "local"  # "local" | "vast"
    vast_url: str = ""
    mysql_dsn: str = "mysql+pymysql://root@localhost:3306/spine_labeling"
    data_dir: str = "./data"

    # TotalSpineSeg is run out-of-process via its own CLI (it pins numpy<2 and
    # pulls in nnU-Net/torchio, which conflict with this backend's deps).
    totalspineseg_bin: str = "totalspineseg"  # CLI name or absolute path
    totalspineseg_data: str = ""  # weights dir; "" -> CLI's packaged default
    seg_device: str = "cpu"  # "cpu" | "cuda" (CLI does not accept "mps")
