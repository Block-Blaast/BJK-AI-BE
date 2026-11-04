# 빌드 컨텍스트는 레포 루트: docker build -f apps/ai/Dockerfile .
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY apps/ai ./apps/ai
COPY apps/server/pyproject.toml ./apps/server/pyproject.toml
RUN uv sync --frozen --no-dev --package bjk-ai

EXPOSE 8001
CMD ["uv", "run", "--no-sync", "uvicorn", "bjk_ai.main:app", "--host", "0.0.0.0", "--port", "8001"]
