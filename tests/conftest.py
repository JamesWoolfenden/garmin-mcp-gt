"""Pytest configuration — stub cloud deps and set env vars before any import."""

import os
import sys
from unittest.mock import MagicMock

for mod in [
    "google",
    "google.cloud",
    "google.cloud.firestore",
    "anthropic",
    "pywebpush",
    "garminconnect",
    "mcp",
    "mcp.server",
    "mcp.server.fastmcp",
]:
    sys.modules.setdefault(mod, MagicMock())

os.environ.setdefault("GARMIN_SIDECAR_URL", "http://localhost:9999")
os.environ.setdefault("GARMIN_API_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("VAPID_PRIVATE_KEY", "test-vapid")
os.environ.setdefault("INTERNAL_SECRET", "correct-secret")
