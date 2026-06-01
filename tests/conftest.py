"""Pytest configuration — stub cloud deps and set env vars before any import."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

for mod in [
    "anthropic",
    "pywebpush",
    "garminconnect",
    "mcp",
    "mcp.server",
    "mcp.server.fastmcp",
    "firebase_admin",
    "firebase_admin.auth",
]:
    sys.modules.setdefault(mod, MagicMock())

# Use in-memory SQLite for tests
os.environ["DB_PATH"] = ":memory:"
os.environ.setdefault("GARMIN_SIDECAR_URL", "http://localhost:9999")
os.environ.setdefault("GARMIN_API_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("VAPID_PRIVATE_KEY", "test-vapid")
os.environ.setdefault("INTERNAL_SECRET", "correct-secret")
