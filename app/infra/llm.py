"""模型工厂：qwen（阿里百炼 OpenAI 兼容接口），temperature=0 保证评测可复现。

M1 实测结论（scripts/probe_qwen.py）：
- bind_tools / parallel_tool_calls=False 直接可用；
- ToolStrategy 必须关闭思考模式（thinking 模式不支持 tool_choice=required），
  且 extra_body 只在构造器级生效，经 bind() 传入无效；
- ProviderStrategy（native json_schema）该模型不支持，勿用。
"""

from langchain_openai import ChatOpenAI

from app.conf.config import settings


def build_model() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_seconds,
        use_responses_api=False,
        extra_body={"enable_thinking": False},
    )
