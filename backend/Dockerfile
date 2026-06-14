FROM python:3.12-slim@sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203

# Install Litestream
RUN apt-get update && apt-get install -y --no-install-recommends wget ca-certificates && \
    wget -qO /tmp/litestream.tar.gz \
      https://github.com/benbjohnson/litestream/releases/download/v0.3.13/litestream-v0.3.13-linux-amd64.tar.gz && \
    tar -xzf /tmp/litestream.tar.gz -C /usr/local/bin/ && \
    rm /tmp/litestream.tar.gz && \
    apt-get remove -y wget && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN mkdir -p /data

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Backend source
COPY backend/main.py backend/db.py backend/garmin_client.py \
     backend/litestream.yml ./
# garmin_mcp.py from repo root (provides _dedup and MCP tools)
COPY garmin_mcp.py ./

ENV PORT=8080
EXPOSE 8080

CMD litestream replicate -exec "uvicorn main:app --host 0.0.0.0 --port ${PORT}"
