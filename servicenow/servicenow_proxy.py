"""ServiceNow MCP Proxy — bridges local stdio MCP to ServiceNow's native remote MCP server with OAuth."""

import json
import os
import sys
import ssl
import hashlib
import secrets
import base64
import urllib.request
import urllib.parse
import urllib.error
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from mcp.server import Server
from mcp.types import Tool, TextContent
import keyring

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from shared.audit import audit_tool_call

KEYRING_SERVICE = "mcp-servicenow"
SERVICENOW_MCP_URL = os.environ.get("SERVICENOW_MCP_URL", "")
SERVICENOW_CLIENT_ID = keyring.get_password(KEYRING_SERVICE, "client_id") or ""
SERVICENOW_CLIENT_SECRET = keyring.get_password(KEYRING_SERVICE, "client_secret") or ""
CALLBACK_PORT = int(os.environ.get("SERVICENOW_CALLBACK_PORT", "80"))

_instance = urllib.parse.urlparse(SERVICENOW_MCP_URL).netloc if SERVICENOW_MCP_URL else ""
AUTH_URL = f"https://{_instance}/oauth_auth.do"
TOKEN_URL = f"https://{_instance}/oauth_token.do"

_ssl_ctx = ssl.create_default_context()
app = Server("servicenow-proxy")

_session_id = None
_access_token = None


def _log(msg):
    print(f"[servicenow-proxy] {msg}", file=sys.stderr, flush=True)


def _load_cached_token():
    access = keyring.get_password(KEYRING_SERVICE, "access_token")
    refresh = keyring.get_password(KEYRING_SERVICE, "refresh_token")
    if access or refresh:
        return {"access_token": access or "", "refresh_token": refresh or ""}
    return None


def _save_token(data):
    if data.get("access_token"):
        keyring.set_password(KEYRING_SERVICE, "access_token", data["access_token"])
    if data.get("refresh_token"):
        keyring.set_password(KEYRING_SERVICE, "refresh_token", data["refresh_token"])


def _exchange_token(grant_params):
    params = {
        "client_id": SERVICENOW_CLIENT_ID,
        "client_secret": SERVICENOW_CLIENT_SECRET,
        **grant_params,
    }
    body = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, context=_ssl_ctx, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    _save_token(data)
    return data["access_token"]


def _refresh_token(refresh_tok):
    return _exchange_token({"grant_type": "refresh_token", "refresh_token": refresh_tok})


def _browser_auth_flow():
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()
    state = secrets.token_urlsafe(32)
    redirect_uri = (
        "http://localhost/callback"
        if CALLBACK_PORT == 80
        else f"http://localhost:{CALLBACK_PORT}/callback"
    )

    auth_params = urllib.parse.urlencode(
        {
            "client_id": SERVICENOW_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
    )

    auth_code = [None]
    auth_error = [None]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if qs.get("state", [None])[0] != state:
                auth_error[0] = "State mismatch"
            elif "error" in qs:
                auth_error[0] = qs["error"][0]
            elif "code" in qs:
                auth_code[0] = qs["code"][0]

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if auth_code[0]:
                self.wfile.write(b"<h2>Authenticated! You can close this tab.</h2>")
            else:
                self.wfile.write(f"<h2>Error: {auth_error[0]}</h2>".encode())

        def log_message(self, *_):
            pass

    srv = HTTPServer(("0.0.0.0", CALLBACK_PORT), Handler)
    srv.timeout = 120

    import webbrowser
    _log("Opening browser for ServiceNow login...")
    webbrowser.open(f"{AUTH_URL}?{auth_params}")

    while auth_code[0] is None and auth_error[0] is None:
        srv.handle_request()
    srv.server_close()

    if auth_error[0]:
        raise RuntimeError(f"OAuth error: {auth_error[0]}")

    return _exchange_token(
        {
            "grant_type": "authorization_code",
            "code": auth_code[0],
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
    )


def _get_access_token():
    cached = _load_cached_token()
    if cached and cached.get("refresh_token"):
        try:
            return _refresh_token(cached["refresh_token"])
        except Exception as e:
            _log(f"Token refresh failed ({e}), re-authenticating...")
    return _browser_auth_flow()


def _mcp_http(method, params=None):
    global _session_id, _access_token

    if _access_token is None:
        _access_token = _get_access_token()

    payload = {"jsonrpc": "2.0", "id": secrets.token_hex(8), "method": method}
    if params is not None:
        payload["params"] = params
    body = json.dumps(payload).encode()

    for attempt in range(2):
        req = urllib.request.Request(SERVICENOW_MCP_URL, data=body, method="POST")
        req.add_header("Authorization", f"Bearer {_access_token}")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        if _session_id:
            req.add_header("Mcp-Session-Id", _session_id)

        try:
            with urllib.request.urlopen(req, context=_ssl_ctx, timeout=60) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    _session_id = sid
                ct = resp.headers.get("Content-Type", "")
                raw = resp.read().decode()

            if "text/event-stream" in ct:
                for line in raw.split("\n"):
                    if line.startswith("data: "):
                        try:
                            return json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue
                return {"error": {"message": "No valid data in SSE response"}}
            return json.loads(raw) if raw.strip() else {}

        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt == 0:
                _log("Token expired, refreshing...")
                cached = _load_cached_token()
                if cached and cached.get("refresh_token"):
                    try:
                        _access_token = _refresh_token(cached["refresh_token"])
                        continue
                    except Exception:
                        pass
                _access_token = _browser_auth_flow()
                continue
            error_body = e.read().decode() if e.fp else str(e)
            raise RuntimeError(f"HTTP {e.code}: {error_body}")

    raise RuntimeError("ServiceNow MCP request failed after token refresh")


def _init_remote():
    result = _mcp_http("initialize", {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "servicenow-proxy", "version": "1.0.0"},
    })

    notify = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    body = json.dumps(notify).encode()
    req = urllib.request.Request(SERVICENOW_MCP_URL, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {_access_token}")
    req.add_header("Content-Type", "application/json")
    if _session_id:
        req.add_header("Mcp-Session-Id", _session_id)
    try:
        with urllib.request.urlopen(req, context=_ssl_ctx, timeout=10) as resp:
            resp.read()
    except Exception:
        pass

    _log(f"Connected to {_instance}")
    return result


_remote_tools = None


def _fetch_tools():
    global _remote_tools
    if _remote_tools is None:
        _init_remote()
        result = _mcp_http("tools/list")
        _remote_tools = result.get("result", {}).get("tools", [])
        _log(f"Loaded {len(_remote_tools)} tools")
    return _remote_tools


@app.list_tools()
async def list_tools():
    loop = asyncio.get_event_loop()
    tools = await loop.run_in_executor(None, _fetch_tools)
    return [
        Tool(
            name=t["name"],
            description=t.get("description", ""),
            inputSchema=t.get("inputSchema", {"type": "object", "properties": {}}),
        )
        for t in tools
    ]


@app.call_tool()
async def call_tool(name, arguments):
    with audit_tool_call("servicenow", name, arguments) as audit:
        loop = asyncio.get_event_loop()

        def _do_call():
            result = _mcp_http("tools/call", {"name": name, "arguments": arguments})
            if "error" in result and "result" not in result:
                return json.dumps(result["error"], indent=2)
            content = result.get("result", {}).get("content", [])
            parts = []
            for c in content:
                if c.get("type") == "text":
                    parts.append(c.get("text", ""))
                else:
                    parts.append(json.dumps(c, indent=2))
            return "\n".join(parts) if parts else json.dumps(
                result.get("result", {}), indent=2
            )

        try:
            text = await loop.run_in_executor(None, _do_call)
        except Exception as e:
            text = json.dumps({"error": True, "message": str(e)}, indent=2)

        return [TextContent(type="text", text=text)]


async def main():
    if not SERVICENOW_MCP_URL:
        _log("ERROR: SERVICENOW_MCP_URL not set")
        sys.exit(1)
    if not SERVICENOW_CLIENT_ID:
        _log("ERROR: SERVICENOW_CLIENT_ID not set")
        sys.exit(1)

    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
