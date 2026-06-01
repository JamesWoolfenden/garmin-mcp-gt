#!/bin/sh
set -e

# Restore latest DB snapshot from GCS (no-op if no replica exists yet)
litestream restore -if-replica-exists -config /app/litestream.yml /data/fuel.db

# Run uvicorn under Litestream so WAL changes are continuously replicated
exec litestream replicate -config /app/litestream.yml \
  -exec "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"
