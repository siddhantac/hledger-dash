# Resolves the app version from git metadata at build time, in its own stage so
# git and .git never end up in the final image.
FROM python:3.12-slim AS version

RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY .git/ ./.git/
RUN git describe --tags --always --dirty > /VERSION 2>/dev/null || echo unknown > /VERSION

FROM python:3.12-slim

# Install hledger via apt (native arm64 + x64 support)
RUN apt-get update && \
    apt-get install -y --no-install-recommends hledger && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY --from=version /VERSION ./VERSION

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
