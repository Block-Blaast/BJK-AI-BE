from fastapi import FastAPI

from bjk_server.api import api_router
from bjk_server.api import dev as dev_api
from bjk_server.config import get_settings
from bjk_server.errors import register_error_handlers


def create_app() -> FastAPI:
    app = FastAPI(title="발주콕 server")
    register_error_handlers(app)
    app.include_router(api_router)
    if get_settings().is_dev:
        app.include_router(dev_api.router)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
