FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim-bookworm
WORKDIR /app

# 安装 git（pr-review 需要）。
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# 从 builder 复制虚拟环境。
COPY --from=builder /app/.venv /app/.venv
COPY . .

# 用虚拟环境中的 uv 安装项目本身。
RUN .venv/bin/uv sync --frozen --no-dev

EXPOSE 8888
ENV PATH="/app/.venv/bin:$PATH"
CMD ["codeinsight", "serve", "--root", "/app", "--port", "8888", "--host", "0.0.0.0"]
