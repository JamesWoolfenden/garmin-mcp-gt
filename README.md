# garmin-sidecar

Thin FastAPI HTTP wrapper over garmin-mcp-gt. Exposes two endpoints for
the Fuel Cloud Run backend to call via Cloudflare Tunnel.

## Setup

### 1. Install dependencies

```shell
pip install fastapi uvicorn garmin-mcp-gt
```

Authenticate Garmin once (if not already done):

```shell
garmin-setup
```

I regsitered wlfdn.dev with cloudflared.

### 2. Set up Cloudflare Tunnel (one-time)

```shell
winget install cloudflare.cloudflared
cloudflared login
cloudflared tunnel create fuel
cloudflared tunnel route dns fuel fuel.wlfdn.dev
```

This creates `~/.cloudflared/fuel.json`. No ports need opening on your router.

### 3. Configure API secret

Edit `start.bat` and set `API_SECRET` to a long random string.
Store the same value in GCP Secret Manager as `garmin-api-secret`.

### 4. Start everything

```shell
start.bat
```

Or add to Task Scheduler: Action = `e:\code\garmin\start.bat`, trigger = at login.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness check — no auth required |
| GET | `/garmin/today` | Steps, active kcal, resting HR, body battery |
| GET | `/garmin/activities` | Today's activities with kcal and duration |

All endpoints except `/health` require header: `X-API-Secret: <your-secret>`

## Response examples

### GET /garmin/today

```json
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
```

### GET /garmin/activities

```json
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
```

## Graceful fallback

If the sidecar is unreachable (desktop off, tunnel down), Cloud Run catches the
connection error and proceeds with food-only balance calculation, noting
"Activity data unavailable" in the recommendation.
