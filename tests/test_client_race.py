"""garmin_mcp.client(): concurrent first calls share one logged-in client."""

import threading
import time

import pytest

import garmin_mcp


class _FakeGarmin:
    instances = 0
    fail = False

    def __init__(self):
        type(self).instances += 1

    def login(self, _dir):
        time.sleep(0.05)  # widen the race window
        if type(self).fail:
            raise RuntimeError("login failed")


@pytest.fixture
def fake(tmp_path, monkeypatch):
    (tmp_path / "tokens.json").write_text("{}")
    monkeypatch.setattr(garmin_mcp, "TOKEN_DIR", str(tmp_path))
    monkeypatch.setattr(garmin_mcp, "_client", None)
    monkeypatch.setattr(garmin_mcp, "Garmin", _FakeGarmin)
    _FakeGarmin.instances = 0
    _FakeGarmin.fail = False
    return _FakeGarmin


def test_concurrent_first_calls_build_one_client(fake):
    results, errors = [], []

    def call():
        try:
            results.append(garmin_mcp.client())
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=call) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert fake.instances == 1
    assert len({id(r) for r in results}) == 1


def test_failed_login_is_not_cached_and_retries(fake):
    fake.fail = True
    with pytest.raises(garmin_mcp.ToolError, match="garmin-setup"):
        garmin_mcp.client()
    assert garmin_mcp._client is None
    fake.fail = False
    assert garmin_mcp.client() is garmin_mcp.client()
    assert fake.instances == 2
