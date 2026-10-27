"""Runs against the real mcp library (no conftest mocks, unlike tests/).

tests/conftest.py stubs `mcp` wholesale, so nothing there can notice an mcp
API break. This does, and mirrors how backend/main.py mounts the server.
"""

import sys
from pathlib import Path

from mcp.server.transport_security import TransportSecuritySettings
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

import garmin_mcp  # noqa: E402

HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def test_tools_registered():
    assert len(garmin_mcp.mcp._tool_manager.list_tools()) >= 10


def test_streamable_http_app_serves_initialize_and_tools_list():
    app = garmin_mcp.mcp.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )
    with TestClient(app) as c:
        init = c.post(
            "/",
            headers=HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"},
                },
            },
        )
        assert init.status_code == 200, init.text
        assert init.json()["result"]["serverInfo"]["name"] == "Garmin"
        tools = c.post(
            "/",
            headers=HEADERS,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
        names = {t["name"] for t in tools.json()["result"]["tools"]}
        assert len(names) >= 10


def test_backend_mount_registers_tools_and_hides_ctx():
    """backend/main.py's /mcp tools must register against the real library.

    Run with the real mcp installed, a tool param typed as starlette Request
    cannot be schema'd; it must be a Context, which is injected and hidden.
    """
    sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
    import os

    for k, v in {
        "DB_PATH": ":memory:",
        "GARMIN_SIDECAR_URL": "http://localhost:9999",
        "GARMIN_API_SECRET": "test-secret",
        "ANTHROPIC_API_KEY": "test-key",
        "VAPID_PRIVATE_KEY": "test-vapid",
        "INTERNAL_SECRET": "test-secret",
        "ALLOWED_EMAILS": "",
        "ADMIN_UID": "test-admin-uid",
    }.items():
        os.environ.setdefault(k, v)
    import main

    mounted = [r for r in main.app.routes if getattr(r, "path", "") == "/mcp"]
    assert mounted, "/mcp was not mounted (see 'MCP server not available' warning)"
    h = {**HEADERS, "Host": "api.example.com"}
    with TestClient(main.app) as c:
        init = c.post(
            "/mcp/",
            headers=h,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"},
                },
            },
        )
        assert init.status_code == 200, init.text
        h["mcp-session-id"] = init.headers["mcp-session-id"]
        c.post(
            "/mcp/",
            headers=h,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        r = c.post(
            "/mcp/",
            headers=h,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
        assert r.status_code == 200, r.text
        body = r.text
        assert "get_today_stats" in body and "get_sedentary_analysis" in body
        assert "ctx" not in body, "Context param leaked into the tool schema"
        call = c.post(
            "/mcp/",
            headers=h,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_today_stats", "arguments": {}},
            },
        )
        assert "isError" in call.text and "steps" not in call.text, call.text
