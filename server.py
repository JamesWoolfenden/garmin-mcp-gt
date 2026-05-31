"""
Garmin HTTP sidecar — exposes a lightweight REST API over garmin_mcp.py.

Runs alongside the MCP server on the same machine. Cloudflared tunnels
inbound requests from Cloud Run to this process. No credentials are exposed —
auth is handled by the existing token store at ~/.garmin_tokens/.

Usage:
    pip install fastapi uvicorn garmin-mcp-gt
    python server.py

Endpoints:
    GET /health           — liveness check
    GET /garmin/today     — active kcal, steps, distance, resting HR
    GET /garmin/activities — today's activities (name, duration, kcal)

Optional env vars:
    PORT              — port to bind (default 8080)
    API_SECRET        — if set, requests must include header X-API-Secret
    GARMIN_TOKEN_DIR  — passed through to garmin_mcp (default ~/.garmin_tokens)
"""

import os
from datetime import date
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

# garmin_mcp must be on PYTHONPATH — if running from the garmin-mcp-gt repo
# root this works automatically. Otherwise install with: pip install garmin-mcp-gt
from garmin_mcp import client, _dedup

app = FastAPI(title="garmin-sidecar", docs_url=None, redoc_url=None)

API_SECRET = os.environ.get("API_SECRET", "")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if API_SECRET and request.url.path != "/health":
        secret = request.headers.get("X-API-Secret", "")
        if secret != API_SECRET:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": "Unauthorized"},
            )
    return await call_next(request)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/garmin/today")
def get_today() -> dict[str, Any]:
    """
    Returns:
    {
        "date": "2026-05-31",
        "active_kcal": 350,
        "total_kcal": 2100,
        "steps": 8200,
        "distance_km": 6.4,
        "active_minutes": 45,
        "resting_hr_bpm": 53,
        "body_battery": {"charged": 72, "drained": 18}
    }
    """
    try:
        today = date.today().isoformat()
        c = client()
        stats = c.get_stats(today)
        hr = c.get_heart_rates(today)
        bb = c.get_body_battery(today)
        battery = {}
        if bb:
            battery = {
                "charged": bb[0].get("charged"),
                "drained": bb[0].get("drained"),
            }
        return {
            "date": today,
            "active_kcal": stats.get("activeKilocalories", 0),
            "total_kcal": stats.get("totalKilocalories", 0),
            "steps": stats.get("totalSteps", 0),
            "distance_km": round(stats.get("totalDistanceMeters", 0) / 1000, 2),
            "active_minutes": stats.get("activeSeconds", 0) // 60,
            "resting_hr_bpm": hr.get("restingHeartRate"),
            "body_battery": battery,
        }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Garmin error: {e}")


@app.get("/garmin/activities")
def get_activities_today() -> dict[str, Any]:
    """
    Returns activities recorded today only.

    {
        "date": "2026-05-31",
        "activities": [
            {
                "name": "Morning ride",
                "type": "road_biking",
                "duration_min": 62,
                "distance_km": 30.1,
                "kcal": 850,
                "avg_power_w": 188
            }
        ],
        "total_active_kcal": 850
    }
    """
    try:
        today = date.today().isoformat()
        c = client()
        raw = c.get_activities(0, 20)
        all_acts = _dedup(raw)
        todays = [a for a in all_acts if a.get("startTimeLocal", "")[:10] == today]
        activities = [
            {
                "name": (a.get("activityName") or "")[:100],
                "type": a.get("activityType", {}).get("typeKey"),
                "duration_min": int(a.get("duration", 0) // 60),
                "distance_km": round(a.get("distance", 0) / 1000, 2),
                "kcal": a.get("calories", 0),
                "avg_power_w": a.get("avgPower"),
            }
            for a in todays
        ]
        total_kcal = sum(a["kcal"] or 0 for a in activities)
        return {
            "date": today,
            "activities": activities,
            "total_active_kcal": total_kcal,
        }
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Garmin error: {e}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
