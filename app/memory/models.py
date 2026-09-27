"""SQLAlchemy ORM：SPEC 第 3 章 DDL 的映射。"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, String, Text, text
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))  # user | bot
    content_type: Mapped[str] = mapped_column(String(16), default="text")  # text | object
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(3), server_default=text("CURRENT_TIMESTAMP(3)")
    )

    __table_args__ = (
        Index("idx_conv_time", "conversation_id", "created_at"),
        Index("idx_run", "run_id"),
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), default="RUNNING")
    reply_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32))
    correction_attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(3), server_default=text("CURRENT_TIMESTAMP(3)")
    )

    __table_args__ = (
        Index("idx_conv", "conversation_id", "created_at"),
        Index("idx_state", "state"),
    )


class AgentToolCall(Base):
    __tablename__ = "agent_tool_calls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BigInteger)
    tool_call_id: Mapped[str] = mapped_column(String(64))
    tool_name: Mapped[str] = mapped_column(String(64))
    arguments: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean)
    failure_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(3), server_default=text("CURRENT_TIMESTAMP(3)")
    )

    __table_args__ = (
        Index("uk_run_call", "run_id", "tool_call_id", unique=True),
        Index("idx_run", "run_id"),
    )
