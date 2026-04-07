# Omni-Track

A self-hosted **Life Operating System** that accepts any data — PDFs, images, voice notes, raw text — and automatically extracts, classifies, and stores structured metrics into a time-series database. A lightweight dashboard surfaces trends and AI-generated weekly insights.

## Architecture

```
┌──────────────────────────────┐
│   MCP Server (FastMCP SSE)   │  ← Any MCP-compatible agent connects here
│   localhost:8000/sse         │
│   8 tools exposed            │
│   SQLite (dev) / PG (prod)   │
└──────────┬───────────────────┘
           │
    ┌──────▼──────┐
    │  omnitrack.db│
    └──────┬──────┘
           │
┌──────────▼───────────────────┐
│  Dashboard API + HTML UI     │
│  localhost:8001               │
└──────────────────────────────┘
```

## Quick Start (Local Dev)

```bash
# 1. Install dependencies
pip install -r mcp/requirements.txt

# 2. Initialize DB & seed test data
cd mcp
python seed_test_data.py

# 3. Start MCP server (terminal 1)
python server.py

# 4. Start dashboard API (terminal 2)
python dashboard_api.py

# 5. Open dashboard
# Open dashboard.html in your browser
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `list_metric_types` | List all registered metric types |
| `upsert_reading` | Insert a reading; auto-creates metric type if new |
| `get_readings` | Fetch time-series for a metric with date range |
| `get_latest` | Most recent reading per metric (filterable by category) |
| `get_all_latest` | Latest reading for every metric + safe ranges |
| `log_insight` | Store a weekly AI insight block |
| `set_safe_range` | Configure safe min/max thresholds per metric |
| `get_safe_ranges` | Read configured thresholds |

### Agent MCP Config

```json
{
  "mcpServers": {
    "omni-track": {
      "url": "http://localhost:8000/sse"
    }
  }
}
```

## Production (Docker)

```bash
cp .env.example .env
# Fill in TELEGRAM_BOT_TOKEN, ANTHROPIC_API_KEY, POSTGRES_PASSWORD
docker compose up -d
# Grafana at localhost:3000, MCP at localhost:8000
```

## Tech Stack

- **MCP Server:** Python + FastMCP (SSE transport)
- **Database:** SQLite (dev) / PostgreSQL 16 (prod)
- **Dashboard:** Vanilla HTML + Chart.js (dev) / Grafana (prod)
- **AI Agent:** Any MCP-compatible agent (OpenClaw, Claude Code, etc.)

## License

MIT
