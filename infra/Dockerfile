# Single container: static web export + FastAPI/voice/jobs. Spec: /architecture/deployment.md (DEP-03)
# Build from the repo root:  docker build -f infra/Dockerfile -t voiceai .

# ---- stage 1: web static export
FROM node:24-slim AS web
WORKDIR /app/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---- stage 2: API runtime
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    FASTEMBED_CACHE=/app/apps/api/.cache/fastembed PORT=8080
RUN pip install --no-cache-dir uv
WORKDIR /app/apps/api
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/api/ ./
RUN uv sync --frozen --no-dev
# specs are read at runtime (prompts, demo knowledge base)
COPY specs/ /app/specs/
COPY --from=web /app/apps/web/out /app/apps/web/out
# bake the embedding model so the first request needs no download
RUN uv run python -c "from voiceai.adapters.embeddings.fastembed import FastEmbedder; FastEmbedder().embed(['warm up'])"
EXPOSE 8080
CMD ["sh", "-c", "uv run --no-sync voiceai serve --host 0.0.0.0 --port ${PORT}"]
