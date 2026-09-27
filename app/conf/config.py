from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config: SettingsConfigDict = SettingsConfigDict(
        env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    # LLM（变量名与 V1 .env 对齐，可直接复用）
    llm_model: str
    llm_base_url: str
    llm_api_key: str
    llm_temperature: float = 0.0
    llm_timeout_seconds: int = 30

    # Database（V2 使用独立库 customer_service_v2）
    database_url: str

    # 电商业务 API
    commerce_api_base_url: str
    commerce_timeout_seconds: int = 10

    # harness 参数（SPEC 9.3：示例默认值；tool_call_limit 从 8 调至 12——
    # M2 实测模型偶发连续发出参数解析失败的调用，8 会提前触发降级）
    history_message_limit: int = 30
    history_character_budget: int = 12000
    max_correction_attempts: int = 2
    tool_call_limit: int = 12
    max_llm_calls_per_turn: int = 4
    pending_confirm_timeout_minutes: int = 30

    # prompt 版本：BASE_PROMPT / SKILL_CATALOG / ACTION_CATALOG 任一变更必须升版本
    prompt_version: str = "v2-agent-1.2.0"

    # 服务器
    app_host: str = "127.0.0.1"
    app_port: int = 18082

    # 数字人（魔珐星云）凭证透传
    digital_human_app_id: str = ""
    digital_human_app_secret: str = ""
    digital_human_gateway_server: str = (
        "https://nebula-agent.xingyun3d.com/user/v1/ttsa/session"
    )


settings = Settings()
