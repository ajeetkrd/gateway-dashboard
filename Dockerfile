# NOTE: NOT used by docker-compose.yaml.
# The gateway instance's Docker Compose plugin is older than buildx 0.17.0, so
# `docker compose up --build` fails there. The compose file instead runs a stock
# python:3.12-slim image and pip-installs at startup (no build step needed).
# This Dockerfile is kept only for reference / if you upgrade buildx and prefer
# to bake a prebuilt image.

FROM python:3.12-slim

WORKDIR /app

# psycopg2-binary ships prebuilt wheels for arm64 and amd64, so no build deps.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
