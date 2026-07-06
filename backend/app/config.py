from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, sourced from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    inference_mode: str = "local"  # "local" | "vast"
    vast_url: str = ""
    mysql_dsn: str = "mysql+pymysql://root@localhost:3306/spine_labeling"
    data_dir: str = "./data"
