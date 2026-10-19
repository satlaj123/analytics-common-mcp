"""Confluence MCP Server with OAuth 2.0 authentication (shared Atlassian Cloud credentials)."""
import json
import time
import urllib.request
import urllib.error
import urllib.parse
import os
import sys
import asyncio
from pathlib import Path
from mcp.server import Server
from mcp.types import Tool, TextContent

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from shared.credentials import get_secret
from shared.audit import audit_tool_call

app = Server("confluence-mcp")

CLOUD_ID = os.environ.get("ATLASSIAN_CLOUD_ID", "")
CONFLUENCE_BASE = f"https://api.atlassian.com/ex/confluence/{CLOUD_ID}/wiki/api/v2"
CONFLUENCE_V1_BASE = f"https://api.atlassian.com/ex/confluence/{CLOUD_ID}/wiki/rest/api"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
TOKEN_FILE = Path(__file__).parent / "confluence_tokens.json"

CLIENT_ID = os.environ.get("ATLASSIAN_CLIENT_ID", "")
CLIENT_SECRET = get_secret("mcp-atlassian", "client_secret", "ATLASSIAN_CLIENT_SECRET")

_token_cache = {"access_token": None, "refresh_token": None, "expires_at": 0}


def _load_tokens():
    if _token_cache["access_token"] and _token_cache["expires_at"] > time.time():
        return
    if TOKEN_FILE.exists():
        data = json.loads(TOKEN_FILE.read_text())
        _token_cache["access_token"] = data.get("access_token")
        _token_cache["refresh_token"] = data.get("refresh_token")
        _token_cache["expires_at"] = data.get("expires_at", 0)


def _save_tokens():
    TOKEN_FILE.write_text(json.dumps({
        "access_token": _token_cache["access_token"],
        "refresh_token": _token_cache["refresh_token"],
        "expires_at": _token_cache["expires_at"],
    }))


def _refresh_access_token():
    data = json.dumps({
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": _token_cache["refresh_token"],
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    _token_cache["access_token"] = result["access_token"]
    _token_cache["expires_at"] = time.time() + result.get("expires_in", 3600) - 60
    if "refresh_token" in result:
        _token_cache["refresh_token"] = result["refresh_token"]
    _save_tokens()


def _get_access_token():
    _load_tokens()
    if not _token_cache["access_token"] or _token_cache["expires_at"] <= time.time():
        _refresh_access_token()
    return _token_cache["access_token"]


def _api_request(base_url, method, path, body=None):
    token = _get_access_token()
    url = f"{base_url}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status == 204:
                return {"status": "success", "code": 204}
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        try:
            error_json = json.loads(error_body)
        except (json.JSONDecodeError, ValueError):
            error_json = {"message": error_body}
        return {"error": True, "status": e.code, "details": error_json}


def _confluence_request(method, path, body=None):
    return _api_request(CONFLUENCE_BASE, method, path, body)


def _confluence_v1_request(method, path, body=None):
    return _api_request(CONFLUENCE_V1_BASE, method, path, body)


@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="confluence_search",
            description="Search Confluence content (pages, blog posts) using CQL",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "CQL query or text search, e.g. 'type=page AND title~\"DME\"' or 'space=IDE AND text~\"pipeline\"'"},
                    "max_results": {"type": "integer", "default": 10, "description": "Maximum results to return"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="confluence_get_page",
            description="Get a Confluence page content by ID. Returns title, body (storage format), version, and space info.",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_id": {"type": "string", "description": "Confluence page ID"},
                },
                "required": ["page_id"],
            },
        ),
        Tool(
            name="confluence_list_spaces",
            description="List available Confluence spaces",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "default": 25, "description": "Maximum spaces to return"},
                },
            },
        ),
        Tool(
            name="confluence_get_space_pages",
            description="List pages in a Confluence space",
            inputSchema={
                "type": "object",
                "properties": {
                    "space_id": {"type": "string", "description": "Confluence space ID (numeric)"},
                    "max_results": {"type": "integer", "default": 25, "description": "Maximum pages to return"},
                },
                "required": ["space_id"],
            },
        ),
        Tool(
            name="confluence_get",
            description="Generic GET from Confluence REST API (v2). Use for any endpoint not covered by other tools.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "API path, e.g. /pages/{id} or /spaces"},
                    "query_params": {"type": "object", "description": "Query parameters as key-value pairs", "additionalProperties": {"type": "string"}},
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="confluence_post",
            description="POST to Confluence REST API (v2). Use for creating pages or comments.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "API path"},
                    "body": {"type": "object", "description": "Request body"},
                },
                "required": ["path", "body"],
            },
        ),
        Tool(
            name="confluence_put",
            description="PUT to Confluence REST API (v2). Use for updating pages.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "API path, e.g. /pages/{id}"},
                    "body": {"type": "object", "description": "Request body"},
                },
                "required": ["path", "body"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name, arguments):
    with audit_tool_call("confluence", name, arguments) as audit:
        loop = asyncio.get_event_loop()

        if name == "confluence_search":
            query = arguments["query"]
            max_results = arguments.get("max_results", 10)
            cql = urllib.parse.quote(query)
            result = await loop.run_in_executor(
                None, lambda: _confluence_v1_request("GET", f"/search?cql={cql}&limit={max_results}")
            )
        elif name == "confluence_get_page":
            page_id = arguments["page_id"]
            result = await loop.run_in_executor(
                None, lambda: _confluence_request("GET", f"/pages/{page_id}?body-format=storage")
            )
        elif name == "confluence_list_spaces":
            max_results = arguments.get("max_results", 25)
            result = await loop.run_in_executor(
                None, lambda: _confluence_request("GET", f"/spaces?limit={max_results}")
            )
        elif name == "confluence_get_space_pages":
            space_id = arguments["space_id"]
            max_results = arguments.get("max_results", 25)
            result = await loop.run_in_executor(
                None, lambda: _confluence_request("GET", f"/spaces/{space_id}/pages?limit={max_results}")
            )
        elif name == "confluence_get":
            path = arguments["path"]
            query_params = arguments.get("query_params")
            if query_params:
                path += "?" + urllib.parse.urlencode(query_params)
            result = await loop.run_in_executor(
                None, lambda: _confluence_request("GET", path)
            )
        elif name == "confluence_post":
            result = await loop.run_in_executor(
                None, lambda: _confluence_request("POST", arguments["path"], arguments.get("body"))
            )
        elif name == "confluence_put":
            result = await loop.run_in_executor(
                None, lambda: _confluence_request("PUT", arguments["path"], arguments.get("body"))
            )
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def main():
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())