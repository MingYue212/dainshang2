


from fastapi import FastAPI

from app.api.routers import router


app = FastAPI()

async def init_app(app: FastAPI):
    pass


app.include_router(router)








