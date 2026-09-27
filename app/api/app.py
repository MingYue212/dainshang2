"""FastAPI 实例：lifespan 管理电商客户端与 DB 引擎生命周期。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routers import router
from app.infra.commerce_client import close_commerce_client
from app.infra.db import dispose_engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_commerce_client()
    await dispose_engine()


app = FastAPI(title="customer-service-v2", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
