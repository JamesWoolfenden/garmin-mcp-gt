# garmin-mcp-gt

Garmin Connect MCP server — exposes your Garmin health and activity data as tools for Claude.

## Tools

| Tool | Description |
|------|-------------|
| `get_today_stats` | Steps, distance, calories, active time, resting HR, body battery |
| `get_recent_activities` | Recent cycling/running activities (de-duplicated) |
| `get_activity_detail` | Detailed metrics, HR zones, and power zones for a specific activity |
| `get_activity_fit` | Downloads the raw FIT file and returns TSS, IF, total work (kJ), device FTP, and per-lap breakdown |
| `get_bike_fit_analysis` | Aggregate fit signals (cadence, L/R balance, power phase, platform offset) across recent rides; compare before/after a bike change with `since=YYYY-MM-DD` |
| `get_ride_fatigue_analysis` | Detect position breakdown under fatigue from per-lap FIT data (PCO drift, cadence drop, power fade) |
| `compare_dual_recordings` | Compare HR and power between two recordings of the same ride on different devices |
| `get_sedentary_analysis` | Sedentary/light/moderate/active time breakdown for a day |
| `get_sleep` | Sleep score, stages, SpO2, and stress for any night |
| `get_hrv` | Overnight HRV readings for the last N days |
| `get_weekly_trends` | Weekly cycling summary with km, hours, and avg power |
| `get_cycling_ftp` | Current FTP and W/kg |
| `get_vo2max` | VO2max and lactate threshold history |
| `get_weight` | Weigh-in history: weight, body fat %, muscle mass |
| `get_weight_trend` | Weekly rolling weight averages to track fat loss without hydration noise |
| `get_weather` | Current conditions and cycling forecast via OpenMeteo (free, no key) — rideable flag per day |
| `get_activity_weather` | Weather recorded by Garmin during a specific past activity |
| `get_courses` | Saved courses from Garmin Connect with distance and elevation |

## Requirements

- Python 3.10+
- A [Garmin Connect](https://connect.garmin.com) account

## Installation

```bash
pip install garmin-mcp-gt
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install garmin-mcp-gt
```

## Setup

Authenticate once to save your session tokens:

```bash
garmin-setup
```

You will be prompted for your Garmin email and password. Tokens are saved to `~/.garmin_tokens/` by default and refreshed automatically.

## Claude Code configuration

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "garmin": {
      "command": "garmin-mcp"
    }
  }
}
```

## Claude Desktop configuration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "garmin": {
      "command": "garmin-mcp"
    }
  }
}
```

On macOS the config file is at:
`~/Library/Application Support/Claude/claude_desktop_config.json`

On Windows:
`%APPDATA%\Claude\claude_desktop_config.json`

### Custom token directory

```json
{
  "mcpServers": {
    "garmin": {
      "command": "garmin-mcp",
      "env": {
        "GARMIN_TOKEN_DIR": "/path/to/tokens"
      }
    }
  }
}
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GARMIN_TOKEN_DIR` | `~/.garmin_tokens/` | Directory where session tokens are stored |

## License

MIT
