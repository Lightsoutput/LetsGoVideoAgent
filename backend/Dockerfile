FROM python:3.12-slim-bookworm AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /uvx /usr/local/bin/

WORKDIR /build/backend

# 先复制依赖清单，业务代码变化时可以继续复用依赖安装缓存。
COPY backend/pyproject.toml backend/README.md ./
COPY backend/src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python \
      ".[agents,infra,media,observability]"


FROM python:3.12-slim-bookworm AS runtime

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000

# ffmpeg/ffprobe 是视频处理的确定性基础工具；tini 负责正确转发退出信号。
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates ffmpeg tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --create-home app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations

RUN mkdir -p /app/data \
    && chown -R app:app /app

USER app

EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["video-agent-api"]
