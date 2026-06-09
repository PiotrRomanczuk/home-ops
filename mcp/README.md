---
created: 2026-06-09
updated: 2026-06-09
---

# home-ops MCP server

Exposes home-ops as an MCP (Model Context Protocol) server so any MCP client
— Claude Desktop, Claude Code, etc. — can read state from home-ops and drive
the local LLM queue running qwen3 on `win10`.

The killer flow:

> _You_ to Claude: "have qwen3 review this function for off-by-ones, in Polish"
>
> Claude → `submit_llm_job(prompt='Sprawdź tę funkcję pod kątem błędów…', model='qwen3:8b')`
>
> 30 seconds later Claude has qwen3's verdict inline. Your code never left your network.

## What you can ask Claude to do once this is wired

- **Drive the local LLM**: "summarise today's warn+ events from guitar-crm using qwen3" — Claude calls `submit_llm_job` with the recent events as prompt.
- **Project intelligence**: "what's next on home-ops?" — Claude calls `get_project('home-ops')`, reads the Now/Next section.
- **Stack health**: "any errors from elitedesk in the last hour?" — Claude calls `query_logs(host='elitedesk', level_min='error', since_min=60)`.
- **Queue introspection**: "what's currently running on win10?" — Claude calls `list_recent_jobs(status='running')` + `get_host_metrics(host='win10')`.
- **VRAM awareness**: "what models are loaded right now?" — Claude calls `models_loaded()` before suggesting a model.

## Tools exposed

| Tool                   | What it does                                                            |
| ---------------------- | ----------------------------------------------------------------------- |
| `query_logs`           | search host_logs by host/source/level/grep/window                       |
| `list_recent_jobs`     | gpu_jobs queue, filter by kind + status                                 |
| `get_job`              | single job state, including `result.response` and `result.thinking`     |
| `submit_llm_job`       | submit + **block until done**; returns response/thinking inline         |
| `cancel_job`           | kill a queued/running job                                               |
| `list_projects`        | all vault-derived projects, filter by status                            |
| `get_project`          | full project state with Now/Next/Later raw markdown                     |
| `get_host_metrics`     | latest metric sample(s) — incl. process attribution in `data` jsonb     |
| `models_loaded`        | what's resident in win10 VRAM right now                                 |

All tools wrap the existing HTTP API at `home-ops-ingest-1`. No new server-side
endpoints; this is purely an MCP-to-REST adapter.

## Install

The server is a single self-contained Python file with PEP 723 inline
metadata. Two ways to run it:

**Option A — `uv` (recommended, zero config)**

```bash
uv run mcp/server.py
```

`uv` reads the PEP 723 metadata at the top of the script and pulls the
`mcp[cli]` dep into an isolated venv. No global install.

**Option B — pip**

```bash
pip install 'mcp[cli]>=1.0'
python3 mcp/server.py
```

## Connect from Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (Mac)
or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "home-ops": {
      "command": "uv",
      "args": ["run", "/Users/piotr/Desktop/MainCV/home-ops/mcp/server.py"],
      "env": {
        "INGEST_URL": "http://elitedesk.tail266853.ts.net:64421/api/ingest",
        "INGEST_TOKEN": "<paste from ~/logs-stack/.env on elitedesk>"
      }
    }
  }
}
```

Restart Claude Desktop. The `home-ops` server should appear in the connector
sidebar with 9 tools available.

**On-LAN tip**: substitute `http://192.168.1.75:64421/api/ingest` for lower
latency. Tailscale-on-LAN works but adds a WireGuard hop. See the home
infrastructure doc for which path to prefer.

## Connect from Claude Code

```bash
claude mcp add home-ops \
  --command uv \
  --args run \
  --args /Users/piotr/Desktop/MainCV/home-ops/mcp/server.py \
  --env INGEST_URL=http://elitedesk.tail266853.ts.net:64421/api/ingest \
  --env INGEST_TOKEN=<secret>
```

Or edit `~/.claude/config` directly with an entry mirroring the Claude Desktop
JSON shape above.

## Security model

- The server is **read-mostly**: 7 of 9 tools are pure reads. The two writes
  (`submit_llm_job` + `cancel_job`) only hit gpu_jobs and only affect your
  own queue.
- Token auth: it presents `X-Ingest-Token` on every call. Same secret as the
  agents. Don't paste this into clients you don't control.
- No vault writes: `get_project` reads project state but there's deliberately
  no `toggle_task` tool — task writeback exists in the UI but is too
  side-effectful to expose through an LLM tool surface without a confirm step.
  Easy to add later if you want it.
- **There's no sandbox on `submit_llm_job`**. Claude can ask qwen3 anything,
  with any model loaded, with any project tag. Treat the MCP server as the
  same trust boundary as the rest of home-ops.

## Smoke test (without a client)

The MCP CLI ships with a dev inspector:

```bash
INGEST_URL=http://elitedesk.tail266853.ts.net:64421/api/ingest \
INGEST_TOKEN=<secret> \
uv run --with 'mcp[cli]' mcp dev mcp/server.py
```

Opens a local web UI where you can call tools manually before wiring it into
a client. Useful for verifying connectivity.

## Failure mode

- If `INGEST_URL` / `INGEST_TOKEN` are unset, the server exits at startup with
  a stderr message. Claude Desktop will show the connector as failed.
- If the HTTP call fails (network, 503), tools return `{"error": "HTTP …"}`
  instead of throwing — the client/LLM sees the error and can decide what to
  do (retry, ask the user, etc.).
- `submit_llm_job` has a 5-minute default timeout. If the job is still running
  when the timeout hits, the server cancels the job and returns
  `{"status": "timeout"}`. For long batch jobs, pass a larger `timeout_sec`.

## Related

- [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) — what the MCP server is wrapping
- [`../docs/CONTEXT.md`](../docs/CONTEXT.md) — data model the tools surface
- [`../clients/`](../clients/) — the non-MCP HTTP clients (Python + Node) for project sprinkles
