# One container: builds the React website, then serves it together with the API (and, with
# TU_AUTORUN=1, runs the research + paper-trading agent around the clock).

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 TU_RUNS_DIR=/data TU_WEB_DIST=/app/web/dist
COPY pyproject.toml README.md ROADMAP.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[backtest,research,web]"
COPY --from=web /web/dist ./web/dist
VOLUME /data
EXPOSE 8000
CMD ["python", "-m", "trading_universe.api", "--port", "8000"]
