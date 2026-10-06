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
    "firebase_admin",
    "firebase_admin.auth",
]:
    sys.modules.setdefault(mod, MagicMock())

# mcp.server.fastmcp needs its own mock: a bare MagicMock's .tool() would
# return a mock rather than the original function, so every @mcp.tool()
# function in garmin_mcp.py would become an opaque mock in tests instead of
# the real, callable function — silently hiding bugs in any of them, the
# same way it hid garmin_mcp.client()'s token-dir bug before that was found.
_fastmcp_mock = MagicMock()
_fastmcp_mock.FastMCP.return_value.tool.return_value.side_effect = lambda fn: fn
sys.modules.setdefault("mcp.server.fastmcp", _fastmcp_mock)

# Use in-memory SQLite for tests
os.environ["DB_PATH"] = ":memory:"
os.environ.setdefault("GARMIN_SIDECAR_URL", "http://localhost:9999")
os.environ.setdefault("GARMIN_API_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("VAPID_PRIVATE_KEY", "test-vapid")
os.environ.setdefault("INTERNAL_SECRET", "correct-secret")
os.environ.setdefault("ALLOWED_EMAILS", "")  # empty = open access in tests
os.environ.setdefault("ADMIN_UID", "test-admin-uid")
