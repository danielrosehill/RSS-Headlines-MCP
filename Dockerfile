FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev
ENV PATH=/app/.venv/bin:$PATH HOST=0.0.0.0 PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8000), 3)"
CMD ["rss-headlines-mcp"]
