"""Runs against the real mcp library (no conftest mocks, unlike tests/).

tests/conftest.py stubs `mcp` wholesale, so nothing there can notice an mcp
API break. This does, and mirrors how backend/main.py mounts the server.
Run it on its own: `python -m pytest tests_integration`.
"""

import hashlib
import os
import sys
from pathlib import Path

import pytest
from mcp.server.transport_security import TransportSecuritySettings
from starlette.testclient import TestClient

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

for _k, _v in {
    "DB_PATH": ":memory:",
    "GARMIN_SIDECAR_URL": "http://localhost:9999",
    "GARMIN_API_SECRET": "test-secret",
    "ANTHROPIC_API_KEY": "test-key",
    "VAPID_PRIVATE_KEY": "test-vapid",
    "INTERNAL_SECRET": "test-secret",
    "ALLOWED_EMAILS": "",
    "ADMIN_UID": "test-admin-uid",
}.items():
    os.environ.setdefault(_k, _v)

import db  # noqa: E402
import garmin_mcp  # noqa: E402

HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "Host": "api.example.com",
}
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "t", "version": "0"},
    },
}


def _call(name, args=None):
    return {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": name, "arguments": args or {}},
    }


def test_stdio_tools_registered():
    assert len(garmin_mcp.mcp._tool_manager.list_tools()) == 19


def test_stdio_server_serves_and_surfaces_tool_error_text(tmp_path, monkeypatch):
    """Anticipated failures must reach the client with their message."""
    monkeypatch.setattr(garmin_mcp, "TOKEN_DIR", str(tmp_path))
    monkeypatch.setattr(garmin_mcp, "_client", None)
    app = garmin_mcp.mcp.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )
    with TestClient(app) as c:
        init = c.post("/", headers=HEADERS, json=INIT)
        assert init.status_code == 200, init.text
        assert init.json()["result"]["serverInfo"]["name"] == "Garmin"
        r = c.post("/", headers=HEADERS, json=_call("get_today_stats"))
        assert "garmin-setup" in r.text, r.text


@pytest.fixture(scope="module")
def web():
    """The real backend app. One TestClient only: the MCP session manager
    can run once per process."""
    import main

    with TestClient(main.app, follow_redirects=False) as c:
        yield main, c


def _user(main, uid, email, key):
    main.register_user(uid, email)
    main.upsert_mcp_api_key(hashlib.sha256(key.encode()).hexdigest(), uid)
    return {**HEADERS, "X-MCP-Key": key}


def test_backend_rejects_requests_without_a_valid_key(web):
    _, c = web
    assert c.post("/mcp/", headers=HEADERS, json=INIT).status_code == 401
    assert c.get("/mcp/", headers=HEADERS).status_code == 401
    bad = {**HEADERS, "X-MCP-Key": "nope"}
    assert c.post("/mcp/", headers=bad, json=INIT).status_code == 401


def test_backend_authenticated_call_reaches_tool_with_the_right_uid(web, monkeypatch):
    main, c = web
    h = _user(main, "u-auth", "a@example.com", "key-auth")
    seen = []
    monkeypatch.setattr(
        main, "_garmin_today", lambda uid: seen.append(uid) or {"steps": 4321}
    )
    assert c.post("/mcp/", headers=h, json=INIT).status_code == 200
    listed = c.post(
        "/mcp/", headers=h, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    )
    assert "get_today_stats" in listed.text and "get_sedentary_analysis" in listed.text
    assert "ctx" not in listed.text, "Context param leaked into the tool schema"
    r = c.post("/mcp/", headers=h, json=_call("get_today_stats"))
    assert r.status_code == 200 and '"isError":true' not in r.text, r.text
    assert "4321" in r.text
    assert seen == ["u-auth"]


def test_backend_serves_exactly_mcp_without_redirect(web):
    main, c = web
    h = _user(main, "u-path", "p@example.com", "key-path")
    r = c.post("/mcp", headers=h, json=INIT)
    assert r.status_code == 200, (r.status_code, r.headers.get("location"))


def test_backend_key_dies_with_the_user(web, monkeypatch):
    main, c = web
    h = _user(main, "u-gone", "g@example.com", "key-gone")
    assert c.post("/mcp/", headers=h, json=INIT).status_code == 200
    monkeypatch.setattr(main.firebase_auth, "update_user", lambda *a, **k: None)
    main.save_garmin_tokens("u-gone", "{}")
    main.admin_delete_user("u-gone", uid="admin")
    assert c.post("/mcp/", headers=h, json=INIT).status_code == 401
    assert main.get_user_for_mcp_key(hashlib.sha256(b"key-gone").hexdigest()) is None
    assert db.load_garmin_tokens("u-gone") is None


def test_backend_key_respects_allowed_emails(web, monkeypatch):
    main, c = web
    h = _user(main, "u-allow", "x@example.com", "key-allow")
    assert c.post("/mcp/", headers=h, json=INIT).status_code == 200
    monkeypatch.setattr(main, "_ALLOWED_EMAILS", {"someone-else@example.com"})
    assert c.post("/mcp/", headers=h, json=INIT).status_code == 401
