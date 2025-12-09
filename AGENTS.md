# AGENTS.md — MCP Server Best Practices (Python / FastMCP) — Codex-First

This file is the operating manual for an agent (Codex) that implements MCP servers in Python.
Goal: MCP servers that are discoverable on-demand, context-efficient, predictable, testable, and deployable over **STDIO** and **Streamable HTTP**.

Core idea: avoid stuffing every tool definition + every intermediate result into the model context. Prefer **progressive disclosure** and **compute/filter in the execution environment**, returning compact results.

---

## 1) Prime directive: context efficiency > everything

1. **Default to small outputs.** If it might be big, return a *summary + handle* (cursor/id/path).
2. **Filter/transform server-side.** Don’t stream 10,000 rows into the model just to filter them.
3. **Progressive disclosure is mandatory.** Every server must implement `search_capabilities(...)` with a `detail` level.
4. **Prefer composable tools.** Many small orthogonal tools beat one mega-tool.
5. **Deterministic behavior.** Stable error codes, stable schemas, stable names.

---

## 2) Hard requirement: standardized progressive disclosure

You are standardizing a discovery pattern across all MCP servers:

### 2.1 Required tool: `search_capabilities`

**Contract**
- Inputs:
  - `query: str` (free text)
  - `detail: Literal["name","summary","full"] = "summary"`
  - `limit: int = 20` (server-enforced max, e.g. 50)
- Output (JSON object):
  - `matches: list[CapabilityMatch]`
  - `count: int`
  - `hint: str | None` (optional “try these queries/tags”)

**Detail levels**
- `name`: tool names only
- `summary`: name + one-liner + tags
- `full`: summary + parameters + return shape + 1 example call + typical output size

**Why**
- Lets Codex find *just* what it needs without loading every tool definition.
- Lets you keep tool descriptions minimal and stable.

### 2.2 Optional but strong: `manifest` resource

Expose a small read-only “server manifest” resource for metadata (name/version/base_url/tags).
Use it for humans and debugging, not as a substitute for `search_capabilities`.

---

## 3) Choose the right surface: tools vs resources vs prompts

### Tools (`@mcp.tool()`)
Use for:
- side effects (create/update/send)
- computation (filter/join/aggregate/convert)
- “verbs” with arguments

**Rule:** tools are small + chainable.

### Resources
Use for:
- read-only access patterns (“GET-like”)
- canonical docs, schemas, configs, snapshots

**Rule:** if it can be large, provide metadata as a resource and an export/transform tool for bulk.

### Prompts
Use for:
- stable instruction templates
Keep prompts short and stable.

---

## 4) Server API design patterns (Codex-optimized)

### 4.1 List/search tools must have these knobs
- `limit` (default 25–50, max 200)
- `cursor` (or offset)
- `fields` (optional selection)
- `detail` (name/summary/full)

### 4.2 “Return small; export big” rule
If output might exceed a few KB:
- return summary + `cursor` or `artifact_path`
- provide a separate export tool (CSV/JSONL/parquet) if bulk is needed

### 4.3 Stable naming
- `snake_case`
- `verb_noun` (e.g. `list_orders`, `get_order`, `update_order_status`)
- never rename tools casually; treat names as API

---

## 5) Reliability contracts (non-negotiable)

### 5.1 Timeouts
All outbound I/O must set explicit timeouts (per request). (Example: 10–30s)

### 5.2 Retries
Retry only when safe:
- idempotent reads
- idempotent writes with idempotency keys
Respect rate limits.

### 5.3 Concurrency
- Use `async def` for I/O tools.
- Reuse clients (HTTP/DB) via lifespan/context when possible.

### 5.4 Logging
For STDIO servers, **stdout is protocol**. Never print debug logs to stdout.
Log to stderr via `logging`.

---

## 6) Error contract

Every tool must:
- validate inputs early
- return or raise an error that includes:
  - `error_code` (stable)
  - `message`
  - `hint` (actionable next step)
  - `request_id` (correlate logs)

Never include secrets or stack traces in returned errors.

Batch tools should return partial results:
```json
{ "ok": [...], "failed": [...], "summary": { "ok": 10, "failed": 2 } }
```

---

## 7) Transport strategy: STDIO + Streamable HTTP

Standard transports include **stdio** and **Streamable HTTP**.
Streamable HTTP is positioned as the production successor to SSE in FastMCP materials.

### 7.1 Single codebase, both paths
- Local dev + Codex harness: **STDIO** (default)
- Remote/prod: **Streamable HTTP** (use `stateless_http` when running multiple replicas)

---

## 8) Canonical Python project setup (uv + mcp)

```bash
uv init my_server
cd my_server
uv venv
source .venv/bin/activate
uv add "mcp[cli]" httpx
```

FastMCP CLI (dev loop, install):
```bash
mcp dev server.py
mcp install server.py
mcp run server.py
```

---

## 9) Canonical server template (ALL servers start here)

This template includes:
- standardized `search_capabilities`
- strict output sizing patterns
- dual transport entrypoint

```python
from __future__ import annotations

import logging
import os
import re
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Optional

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mcp")

mcp = FastMCP("my_server")

# -----------------------------
# Capability index (source of truth)
# -----------------------------

Detail = Literal["name", "summary", "full"]

@dataclass(frozen=True)
class Capability:
    name: str                 # tool name
    summary: str              # one-liner
    tags: tuple[str, ...]     # searchable tags
    args: dict[str, str]      # param -> type (stringified)
    returns: str              # return type (stringified)
    example: dict[str, Any]   # example call args
    typical_bytes: int        # typical response size (rough)

CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        name="search_capabilities",
        summary="Search tools exposed by this server with progressive detail levels.",
        tags=("meta", "discovery", "progressive-disclosure"),
        args={"query": "str", "detail": "Literal['name','summary','full']", "limit": "int"},
        returns="dict[str, Any]",
        example={"query": "forecast", "detail": "summary", "limit": 10},
        typical_bytes=1200,
    ),
    # Add one entry per tool you expose.
)

def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

def _match_score(q: str, cap: Capability) -> int:
    if not q:
        return 0
    qn = _normalize(q)
    hay = " ".join([cap.name, cap.summary, " ".join(cap.tags)])
    hn = _normalize(hay)
    score = 0
    for token in qn.split():
        if token in hn:
            score += 1
    return score

@mcp.tool()
def search_capabilities(query: str, detail: Detail = "summary", limit: int = 20) -> dict[str, Any]:
    # Progressive disclosure index:
    # - detail=name: tool names only
    # - detail=summary: name + summary + tags
    # - detail=full: + args/returns/example/typical_bytes
    request_id = str(uuid.uuid4())
    limit = max(1, min(int(limit), 50))

    scored = [(c, _match_score(query, c)) for c in CAPABILITIES]
    if query.strip():
        scored = [x for x in scored if x[1] > 0]
        scored.sort(key=lambda t: (-t[1], t[0].name))
    else:
        scored.sort(key=lambda t: t[0].name)

    matches = []
    for cap, _score in scored[:limit]:
        if detail == "name":
            matches.append({"name": cap.name})
        elif detail == "summary":
            matches.append({"name": cap.name, "summary": cap.summary, "tags": list(cap.tags)})
        else:
            matches.append({
                "name": cap.name,
                "summary": cap.summary,
                "tags": list(cap.tags),
                "args": cap.args,
                "returns": cap.returns,
                "example": cap.example,
                "typical_bytes": cap.typical_bytes,
            })

    return {
        "request_id": request_id,
        "query": query,
        "detail": detail,
        "count": len(matches),
        "matches": matches,
        "hint": "Use detail='name' for minimal context; detail='full' only when implementing a call.",
    }

# -----------------------------
# Example I/O helper (pattern)
# -----------------------------

DEFAULT_TIMEOUT_S = 20.0

async def http_get_json(url: str, *, headers: Optional[dict[str, str]] = None) -> dict[str, Any]:
    async with httpx.AsyncClient(follow_redirects=True, timeout=DEFAULT_TIMEOUT_S) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return r.json()

# -----------------------------
# Dual transport entrypoint
# -----------------------------

def main() -> None:
    # Default: stdio (Codex/local)
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()

    if transport == "stdio":
        mcp.run(transport="stdio")
        return

    # Streamable HTTP (prod/remote)
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    path = os.getenv("MCP_PATH", "/mcp")
    stateless_http = os.getenv("STATELESS_HTTP", "1") == "1"
    json_response = os.getenv("JSON_RESPONSE", "1") == "1"

    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
        path=path,
        stateless_http=stateless_http,
        json_response=json_response,
    )

if __name__ == "__main__":
    main()
```

---

## 10) Codex implementation protocol (how the agent should work)

When asked to add features/tools to a server:

1) **Update CAPABILITIES first**
- Add an entry for the new tool before writing the tool.
- Decide default output size and “detail knobs”.

2) **Write core logic as pure functions**
- Put side-effect free logic in `core.py`.
- MCP tool functions in `server.py` should be thin wrappers.
This makes unit tests trivial.

3) **Add tool wrapper**
- typed args, short docstring, deterministic output
- include `limit/cursor/detail` if the tool can return lists

4) **Write tests**
- unit tests for core logic
- contract tests for tool output shapes

5) **Manual smoke via Inspector**
- `mcp dev server.py` to inspect schema and failure modes.

---

## 11) Testing harness (pytest contracts)

The goal is: “tool works” AND “tool returns what downstream code expects”.

### 11.1 Suggested structure
```
my_server/
  src/my_server/
    server.py
    core.py
  tests/
    test_core_*.py
    test_tools_contract_*.py
  pyproject.toml
```

### 11.2 Contract test example (shape + limits)
```python
# tests/test_tools_contract_discovery.py
from my_server.server import search_capabilities

def test_search_capabilities_minimal():
    out = search_capabilities(query="capabilities", detail="name", limit=5)
    assert "matches" in out and isinstance(out["matches"], list)
    assert len(out["matches"]) <= 5
    assert all("name" in m for m in out["matches"])

def test_search_capabilities_full_is_richer():
    out = search_capabilities(query="", detail="full", limit=50)
    assert out["count"] == len(out["matches"])
    if out["matches"]:
        m = out["matches"][0]
        assert "args" in m and "returns" in m and "example" in m
```

### 11.3 I/O tools: mock upstream
Use `respx` to mock `httpx` for deterministic tests. Keep tests offline.

---

## 12) Definition of done

A server is “done” when:
- `search_capabilities` exists and is accurate (matches reality)
- list/search tools have `limit` and default small outputs
- no stdout logging
- errors are structured and actionable
- pytest contract tests pass
- runs in stdio and streamable-http modes

---

## References (read these once; then encode them into patterns)

- Anthropic: “Code execution with MCP: Building more efficient agents”
  - https://www.anthropic.com/engineering/code-execution-with-mcp
- MCP docs: “Build an MCP server”
  - https://modelcontextprotocol.io/docs/develop/build-server
- MCP spec (Transports)
  - https://modelcontextprotocol.io/specification/2025-03-26/basic/transports
- MCP Python SDK / FastMCP notes (CLI, streamable-http)
  - https://pypi.org/project/mcp/
- FastMCP server API (run, run_http_async, get_tools)
  - https://gofastmcp.com/python-sdk/fastmcp-server-server
