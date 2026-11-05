# 빌드 컨텍스트는 레포 루트: docker build -f apps/server/Dockerfile .
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv

# 결재용 PDF(WeasyPrint)의 pango와 한글 글꼴 (REV-07)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY apps/server ./apps/server
COPY apps/ai/pyproject.toml ./apps/ai/pyproject.toml
RUN uv sync --frozen --no-dev --package bjk-server

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "bjk_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
