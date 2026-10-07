FROM python:3.12-slim@sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203

# Install Litestream. wget/ca-certificates are intentionally unpinned: the
# base image above is pinned by digest (the durable reproducibility anchor),
# but an exact apt version pin here goes stale as soon as Debian's trixie
# repo rolls forward past it — apt has no fallback to an older version once
# that happens, so the build just breaks outright. wget is removed again in
# this same layer anyway (build-time only), and a fresher ca-certificates is
# strictly better for TLS trust than freezing an old one.
# holden:ignore:HLD_DF_020
RUN apt-get update && apt-get install -y --no-install-recommends \
      wget ca-certificates && \
    wget -qO /tmp/litestream.tar.gz \
      https://github.com/benbjohnson/litestream/releases/download/v0.3.13/litestream-v0.3.13-linux-amd64.tar.gz && \
    tar -xzf /tmp/litestream.tar.gz -C /usr/local/bin/ && \
    rm /tmp/litestream.tar.gz && \
    apt-get remove -y wget && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --create-home --home-dir /app app && \
    mkdir -p /data && chown -R app:app /app /data

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Backend source
COPY backend/main.py backend/db.py backend/garmin_client.py \
     backend/litestream.yml ./
# garmin_mcp.py from repo root (provides _dedup and MCP tools)
COPY garmin_mcp.py ./

RUN chown -R app:app /app /data

ENV PORT=8080
EXPOSE 8080

USER app

CMD ["/bin/sh", "-c", "litestream restore -config /app/litestream.yml -if-replica-exists /data/fuel.db; litestream replicate -config /app/litestream.yml -exec \"uvicorn main:app --host 0.0.0.0 --port $PORT\""]
