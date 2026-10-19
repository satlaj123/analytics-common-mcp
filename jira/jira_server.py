"""Jira MCP Server with OAuth 2.0 authentication."""

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

app = Server("jira-mcp")

CLOUD_ID = os.environ.get("ATLASSIAN_CLOUD_ID", "")
BASE_URL = f"https://api.atlassian.com/ex/jira/{CLOUD_ID}"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
TOKEN_FILE = Path(__file__).parent / "jira_tokens.json"

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
    req = urllib.request.Request(
        TOKEN_URL, data=data, headers={"Content-Type": "application/json"}
    )
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


def _jira_request(method, path, query_params=None, body=None):
    token = _get_access_token()
    url = f"{BASE_URL}{path}"
    if query_params:
        url += "?" + urllib.parse.urlencode(query_params)

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


@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="jira_get",
            description="GET from Jira REST API. Common paths: /rest/api/3/project, /rest/api/3/search/jql (use jql query param), /rest/api/3/issue/{key}",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "API path, e.g. /rest/api/3/project"},
                    "query_params": {
                        "type": "object",
                        "description": "Query parameters as key-value pairs",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="jira_post",
            description="POST to Jira REST API. Use for creating issues, adding comments, transitioning issues.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "API path"},
                    "body": {"type": "object", "description": "Request body"},
                    "query_params": {
                        "type": "object",
                        "description": "Query parameters",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["path", "body"],
            },
        ),
        Tool(
            name="jira_put",
            description="PUT to Jira REST API. Use for full resource updates.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "API path"},
                    "body": {"type": "object", "description": "Request body"},
                    "query_params": {
                        "type": "object",
                        "description": "Query parameters",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["path", "body"],
            },
        ),
        Tool(
            name="jira_search",
            description="Search Jira issues using JQL. Returns key, summary, status, assignee, and priority.",
            inputSchema={
                "type": "object",
                "properties": {
                    "jql": {
                        "type": "string",
                        "description": "JQL query, e.g. 'project=DMET AND status=\"In Progress\"'",
                    },
                    "max_results": {"type": "integer", "description": "Max results (default 20)", "default": 20},
                    "fields": {
                        "type": "string",
                        "description": "Comma-separated fields (default: summary,status,assignee,priority)",
                    },
                },
                "required": ["jql"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name, arguments):
    with audit_tool_call("jira", name, arguments) as audit:
        loop = asyncio.get_event_loop()

        if name == "jira_get":
            result = await loop.run_in_executor(
                None,
                lambda: _jira_request("GET", arguments["path"], arguments.get("query_params")),
            )
        elif name == "jira_post":
            result = await loop.run_in_executor(
                None,
                lambda: _jira_request(
                    "POST", arguments["path"], arguments.get("query_params"), arguments.get("body")
                ),
            )
        elif name == "jira_put":
            result = await loop.run_in_executor(
                None,
                lambda: _jira_request(
                    "PUT", arguments["path"], arguments.get("query_params"), arguments.get("body")
                ),
            )
        elif name == "jira_search":
            jql = arguments["jql"]
            max_results = str(arguments.get("max_results", 20))
            fields = arguments.get("fields", "summary,status,assignee,priority")
            params = {"jql": jql, "maxResults": max_results, "fields": fields}
            result = await loop.run_in_executor(
                None, lambda: _jira_request("GET", "/rest/api/3/search/jql", params)
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
