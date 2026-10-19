"""One-time OAuth 2.0 authorization for Confluence.

Usage:
    python confluence_auth.py
"""

import json
import os
import time
import urllib.request
import urllib.parse
import http.server
import threading
import webbrowser
from pathlib import Path

CLIENT_ID = os.environ.get("ATLASSIAN_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("ATLASSIAN_CLIENT_SECRET", "")
REDIRECT_URI = "http://localhost:8080/callback"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
TOKEN_FILE = Path(__file__).parent / "confluence_tokens.json"

SCOPES = [
    "offline_access",
    "read:page:confluence",
    "write:page:confluence",
    "read:space:confluence",
    "read:content:confluence",
    "search:confluence",
]

auth_code = None


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        auth_code = params.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h2>Authorization successful! You can close this tab.</h2>")

    def log_message(self, format, *args):
        pass


def main():
    global auth_code

    auth_url = (
        "https://auth.atlassian.com/authorize?"
        + urllib.parse.urlencode({
            "audience": "api.atlassian.com",
            "client_id": CLIENT_ID,
            "scope": " ".join(SCOPES),
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "prompt": "consent",
            "state": "confluence_setup",
        })
    )
    
    server = http.server.HTTPServer(("localhost", 8080), CallbackHandler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    print("Opening browser for Confluence authorization...")
    print(f"\nIf the browser doesn't open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    thread.join(timeout=120)
    server.server_close()

    if not auth_code:
        print("ERROR: No authorization code received. Timed out or denied.")
        return

    print("Got authorization code, exchanging for tokens...")

    data = json.dumps({
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": auth_code,
        "redirect_uri": REDIRECT_URI,
    }).encode()

    req = urllib.request.Request(
        TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"\nERROR: Token exchange failed ({e.code})")
        print(error_body)
        return

    tokens = {
        "access_token": result["access_token"],
        "refresh_token": result["refresh_token"],
        "expires_at": time.time() + result.get("expires_in", 3600) - 60,
    }
    TOKEN_FILE.write_text(json.dumps(tokens))
    print(f"\nTokens saved to {TOKEN_FILE}")
    print("Confluence MCP server is ready to use!")


if __name__ == "__main__":
    main()
