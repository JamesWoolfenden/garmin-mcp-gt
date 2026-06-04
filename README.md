# Fuel

A calorie and activity tracker for cyclists, powered by Claude and Garmin Connect.

Log food in plain English, get a calorie balance against your activity, and ask questions about your fitness data — all from a mobile-friendly web app.

<img src="docs/screenshot-app.png" alt="Fuel app — food log view" width="390" />

## Features

- **Food logging** — describe what you ate in plain English; Claude estimates the calories
- **Activity balance** — live calorie in vs. burned, updated from Garmin
- **Conversational health advisor** — ask "how were my steps today?" or "how did I sleep last night?" and get answers using your real Garmin data
- **Push nudges** — scheduled notifications with time-aware advice (morning vs. evening)
- **Multi-user** — each user has their own data, secured with Firebase Auth

## Using the app

The hosted app is at **https://pike-477416.web.app**

1. Sign in with Google or create an email/password account
2. Log food in the text box ("had porridge and a coffee")
3. Connect Garmin to enable activity data and the Ask tab (see below)
4. Tap **Ask** to chat with Claude about your health data

## Connecting Garmin

Garmin uses session tokens that must be generated on your own machine (there is no public OAuth API). Setup takes about two minutes:

### 1. Install the CLI

```bash
pip install garmin-mcp-gt
```

### 2. Authenticate with Garmin

```bash
garmin-setup
```

Enter your Garmin Connect email and password when prompted. Tokens are saved to `~/.garmin_tokens/`.

### 3. Generate an upload token in the app

In the Fuel app, scroll to the bottom of the **Log** tab and tap **Connect Garmin**. This generates a 15-minute upload token.

### 4. Upload your tokens

```bash
garmin-upload-tokens --token "paste-token-here"
```

That's it. Your Garmin data is now available in the app and the Ask tab will use it.

**Tokens expire** periodically (weeks to months). Re-run `garmin-setup` then `garmin-upload-tokens` when needed.

## Using with Claude Code / Claude Desktop

`garmin-mcp-gt` is also an MCP server for use in Claude Code sessions. After `pip install garmin-mcp-gt` and `garmin-setup`, add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "garmin": {
      "command": "garmin-mcp-gt"
    }
  }
}
```

Then ask Claude things like "am I sedentary today?" or "how does my sleep affect my training load?".

## Architecture

- **Frontend** — React PWA, hosted on Firebase Hosting
- **Backend** — FastAPI on Cloud Run (europe-west1)
- **Database** — SQLite with Litestream replication to GCS (zero managed DB cost)
- **Garmin tokens** — encrypted at rest with Cloud KMS, per-user in SQLite
- **Auth** — Firebase Auth (Google Sign-In + email/password)
- **AI** — Claude API (food parsing, recommendations, conversational tools)

## Self-hosting

The backend is a standard Cloud Run service. To deploy your own instance:

1. Fork this repo
2. Create a GCP project and enable the required APIs
3. Run `backend/setup-wif.ps1` to configure GitHub Actions auth
4. Run `backend/setup-secrets.ps1` to store your secrets
5. Add GitHub Actions secrets (see `backend/setup-wif.ps1` output)
6. Push to main — CI deploys everything automatically

Infrastructure is managed with OpenTofu — see `terraform/`.

## Development

```bash
# Python tests
python -m pytest

# Frontend tests
cd ui && npm test

# Run backend locally
DB_PATH=./dev.db uvicorn backend.main:app --reload
```
