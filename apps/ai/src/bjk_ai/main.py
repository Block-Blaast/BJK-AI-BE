from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="발주콕 ai")

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
