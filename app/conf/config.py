from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).parents[2] / ".env"

print(ENV_FILE)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    # LLM
    llm_model: str
    llm_base_url: str
    llm_api_key: str

    # Database
    database_url: str

    # 电商业务base_url
    commerce_api_base_url: str

    # 服务器
    app_host: str
    app_port: int


settings = Settings()

if __name__ == "__main__":
    print(settings.app_port)
