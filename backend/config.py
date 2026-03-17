from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    OPENAI_API_KEY: str = ""
    ENVIRONMENT: str = "development"
    FASTAPI_PORT: int = 8010
    STREAMLIT_PORT: int = 8511
    HETZNER_SERVER_IP: str = ""
    HETZNER_SSH_USER: str = "root"
    HETZNER_SSH_KEY_PATH: str = "~/.ssh/id_rsa"
    UPLOAD_DIR: str = "./uploads"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
