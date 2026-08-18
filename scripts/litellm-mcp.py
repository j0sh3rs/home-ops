#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "mcp[cli]>=1.2.0,<2.0.0",
#     "httpx>=0.27",
# ]
# ///
"""Thin MCP wrapper around the LiteLLM proxy Admin API.

Config via env vars (see litellm-mcp.env):
  LITELLM_API_BASE   e.g. https://litellm.68cc.io
  LITELLM_MASTER_KEY sk-...
"""
import os
import re
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

# Load repo-root litellm-mcp.env directly -- don't rely on the launching
# process (e.g. Claude Code) having sourced mise's shell env first.
_env_file = Path(__file__).resolve().parent.parent / "litellm-mcp.env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _m = re.match(r'^export\s+([A-Za-z_][A-Za-z0-9_]*)=(.*)$', _line.strip())
        if _m:
            os.environ.setdefault(_m.group(1), _m.group(2))

API_BASE = os.environ["LITELLM_API_BASE"].rstrip("/")
MASTER_KEY = os.environ["LITELLM_MASTER_KEY"]

mcp = FastMCP("litellm")

client = httpx.Client(
    base_url=API_BASE,
    headers={"Authorization": f"Bearer {MASTER_KEY}"},
    timeout=30.0,
)


def _call(method: str, path: str, json_body: dict | None = None, params: dict | None = None) -> dict:
    resp = client.request(method.upper(), path, json=json_body, params=params)
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text}
    if resp.is_error:
        return {"error": resp.status_code, "detail": data}
    return data


@mcp.tool()
def litellm_request(method: str, path: str, body: dict | None = None, params: dict | None = None) -> dict:
    """Call any LiteLLM Admin API endpoint directly.

    method: GET/POST/PUT/PATCH/DELETE
    path: endpoint path, e.g. "/model/new", "/key/generate", "/global/spend"
    body: JSON request body (for POST/PUT)
    params: query string params (for GET)
    Full endpoint list: GET {LITELLM_API_BASE}/openapi.json
    """
    return _call(method, path, json_body=body, params=params)


@mcp.tool()
def list_models() -> dict:
    """List all models currently configured on the LiteLLM proxy."""
    return _call("GET", "/model/info")


@mcp.tool()
def add_model(model_name: str, litellm_params: dict, model_info: dict | None = None) -> dict:
    """Register a new model on the proxy.

    model_name: alias clients will request (e.g. "gpt-4o")
    litellm_params: e.g. {"model": "openai/gpt-4o", "api_base": "...", "api_key": "..."}
    model_info: optional metadata dict
    """
    body = {"model_name": model_name, "litellm_params": litellm_params}
    if model_info:
        body["model_info"] = model_info
    return _call("POST", "/model/new", json_body=body)


@mcp.tool()
def update_model(model_id: str, model_name: str, litellm_params: dict) -> dict:
    """Update an existing model's config. model_id comes from list_models()."""
    body = {"model_name": model_name, "litellm_params": litellm_params, "model_info": {"id": model_id}}
    return _call("POST", "/model/update", json_body=body)


@mcp.tool()
def delete_model(model_id: str) -> dict:
    """Delete a model by its id (from list_models())."""
    return _call("POST", "/model/delete", json_body={"id": model_id})


@mcp.tool()
def list_keys(page: int = 1, size: int = 50) -> dict:
    """List virtual API keys issued by the proxy."""
    return _call("GET", "/key/list", params={"page": page, "size": size})


@mcp.tool()
def generate_key(
    models: list[str] | None = None,
    key_alias: str | None = None,
    max_budget: float | None = None,
    duration: str | None = None,
) -> dict:
    """Create a new virtual API key.

    models: restrict key to these model names (omit for all)
    max_budget: USD spend cap
    duration: e.g. "30d", "24h"
    """
    body = {}
    if models is not None:
        body["models"] = models
    if key_alias is not None:
        body["key_alias"] = key_alias
    if max_budget is not None:
        body["max_budget"] = max_budget
    if duration is not None:
        body["duration"] = duration
    return _call("POST", "/key/generate", json_body=body)


@mcp.tool()
def delete_key(key: str) -> dict:
    """Revoke a virtual API key."""
    return _call("POST", "/key/delete", json_body={"keys": [key]})


@mcp.tool()
def spend_summary(start_date: str | None = None, end_date: str | None = None) -> dict:
    """Global spend report. Dates as YYYY-MM-DD; omit for all-time."""
    params = {}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return _call("GET", "/global/spend/report", params=params)


@mcp.tool()
def health_check() -> dict:
    """Check health of all configured LLM backends behind the proxy."""
    return _call("GET", "/health")


if __name__ == "__main__":
    mcp.run()
