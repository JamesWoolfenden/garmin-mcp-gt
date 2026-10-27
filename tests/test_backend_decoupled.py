"""The backend must not depend on the stdio MCP server module.

garmin_mcp imports the mcp library at module level; anything the backend takes
from it would make an mcp breakage take down unrelated endpoints (/balance, the
weekly digest, the cycling forecast...). Shared helpers live in garmin_core.
"""

import ast
from pathlib import Path

import garmin_core

ROOT = Path(__file__).parent.parent


def test_backend_never_imports_garmin_mcp():
    for f in (ROOT / "backend").glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert "garmin_mcp" not in names, f"{f.name}:{node.lineno}"


def test_garmin_core_is_free_of_mcp_and_garmin_client():
    tree = ast.parse((ROOT / "garmin_core.py").read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add((node.module or "").split(".")[0])
    assert not mods & {"mcp", "garminconnect", "garmin_mcp"}, mods


def test_image_ships_garmin_core_and_the_wheel_includes_it():
    assert "COPY garmin_core.py" in (ROOT / "backend/Dockerfile").read_text()
    assert "garmin_core.py" in (ROOT / "pyproject.toml").read_text()


class _FakeSession:
    def __init__(self, raw):
        self.raw = raw
        self.calls = []

    def connectapi(self, path, params=None):
        self.calls.append((path, params))
        return self.raw


def test_courses_from_uses_the_given_session_and_clamps_limit():
    g = _FakeSession(
        {
            "courseList": [
                {
                    "courseId": 7,
                    "courseName": "Loop",
                    "activityType": {"typeKey": "road_biking"},
                    "distanceInMeters": 42500,
                    "elevationGainInMeters": 310,
                    "createdDateFormatted": "2026-10-01T09:00:00",
                }
            ]
        }
    )
    out = garmin_core.courses_from(g, 500)
    assert g.calls == [("/course-service/course", {"start": 0, "limit": 100})]
    assert out == [
        {
            "course_id": 7,
            "name": "Loop",
            "type": "road_biking",
            "distance_km": 42.5,
            "elevation_gain_m": 310,
            "created": "2026-10-01",
        }
    ]
    assert garmin_core.courses_from(_FakeSession(None), 5) == []
