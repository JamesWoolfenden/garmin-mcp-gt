# garmin-mcp-gt

Garmin Connect MCP server — exposes your Garmin health and activity data as tools for Claude.

<img src="docs/screenshot-app.png" alt="Fuel app — food log view" width="390" />

## Tools

| Tool | Description |
|------|-------------|
| `get_today_stats` | Steps, distance, calories, active time, resting HR, body battery |
| `get_recent_activities` | Recent cycling/running activities (de-duplicated) |
| `get_activity_detail` | Detailed metrics, HR zones, and power zones for a specific activity |
| `get_sleep` | Sleep score, stages, SpO2, and stress for any night |
| `get_hrv` | Overnight HRV readings for the last N days |
| `get_weekly_trends` | Weekly cycling summary with km, hours, and avg power |

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

## Claude Desktop configuration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "garmin": {
      "command": "garmin-mcp-gt"
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
      "command": "garmin-mcp-gt",
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
