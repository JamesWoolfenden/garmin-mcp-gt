"""Chat's get_weather falls back to the profile's saved location."""

import backend.main as m


def _call(monkeypatch, profile, tool_input):
    seen = {}

    def fake_weather(**kw):
        seen.update(kw)
        return {"ok": True}

    import garmin_core

    monkeypatch.setattr(garmin_core, "get_weather", fake_weather)
    monkeypatch.setattr(m, "get_profile", lambda uid: profile)
    out = m._execute_garmin_tool("get_weather", tool_input, "u1", object())
    return out, seen


def test_uses_profile_location_when_omitted(monkeypatch):
    out, seen = _call(monkeypatch, {"latitude": 51.45, "longitude": -0.97}, {"days": 2})
    assert out == {"ok": True}
    assert (seen["latitude"], seen["longitude"], seen["days"]) == (51.45, -0.97, 2)


def test_explicit_location_wins(monkeypatch):
    _, seen = _call(
        monkeypatch,
        {"latitude": 51.45, "longitude": -0.97},
        {"latitude": 1.0, "longitude": 2.0},
    )
    assert (seen["latitude"], seen["longitude"]) == (1.0, 2.0)


def test_location_not_set_is_reported(monkeypatch):
    out, seen = _call(monkeypatch, {"latitude": None, "longitude": None}, {})
    assert out["error"] == "location_not_set"
    assert not seen

