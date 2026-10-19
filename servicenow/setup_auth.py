"""One-time setup: authenticate with ServiceNow and store tokens in Windows Credential Manager."""

import json
import os
import sys
import ssl
import hashlib
import secrets
import base64
import urllib.request
import urllib.parse
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import keyring

KEYRING_SERVICE = "mcp-servicenow"
MCP_URL = os.environ.get(
    "SERVICENOW_MCP_URL",
    "https://kochdev.service-now.com/sncapps/mcp-server/mcp/x_koi_ent_it_mcp_itsm_fulfiller",
)
CLIENT_ID = keyring.get_password(KEYRING_SERVICE, "client_id") or ""
CLIENT_SECRET = keyring.get_password(KEYRING_SERVICE, "client_secret") or ""
CALLBACK_PORT = 80

_instance = urllib.parse.urlparse(MCP_URL).netloc
AUTH_URL = f"https://{_instance}/oauth_auth.do"
TOKEN_URL = f"https://{_instance}/oauth_token.do"
_ssl_ctx = ssl.create_default_context()


def main():
    print("ServiceNow MCP Auth Setup")
    print(f"Instance: {_instance}")
    print(
        f"Client ID: {CLIENT_ID[:8]}...{CLIENT_ID[-4:]}"
        if CLIENT_ID
        else "Client ID: NOT SET"
    )
    print()

    if not CLIENT_ID or not CLIENT_SECRET:
        print("ERROR: Credentials not found in Windows Credential Manager.")
        print("Run this first:")
        print(
            """  python -c "import keyring; keyring.set_password('mcp-servicenow', 'client_id', 'YOUR_ID')" """
        )
        print(
            """  python -c "import keyring; keyring.set_password('mcp-servicenow', 'client_secret', 'YOUR_SECRET')" """
        )
        sys.exit(1)

    existing_access = keyring.get_password(KEYRING_SERVICE, "access_token")
    if existing_access:
        print("Existing token found in Credential Manager.")
        resp = input("Re-authenticate? [y/N]: ").strip().lower()
        if resp != "y":
            print("Keeping existing token.")
            return

    code_verifier = secrets.token_urlsafe(64)
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    state = secrets.token_urlsafe(32)
    redirect_uri = "http://localhost/callback"

    auth_params = urllib.parse.urlencode(
        {
            "client_id": CLIENT_ID,
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
                auth_error[0] = qs.get("error_description", qs["error"])[0]
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

    print(f"Starting callback server on port {CALLBACK_PORT}...")
    srv = HTTPServer(("0.0.0.0", CALLBACK_PORT), Handler)
    srv.timeout = 120

    print("Opening browser for ServiceNow login...")
    webbrowser.open(f"{AUTH_URL}?{auth_params}")
    print("Waiting for login (2 minute timeout)...")

    while auth_code[0] is None and auth_error[0] is None:
        srv.handle_request()
    srv.server_close()

    if auth_error[0]:
        print(f"ERROR: {auth_error[0]}")
        sys.exit(1)

    print("Got authorization code, exchanging for token...")

    token_params = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": auth_code[0],
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
    ).encode()

    req = urllib.request.Request(TOKEN_URL, data=token_params, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, context=_ssl_ctx, timeout=30) as resp:
            token_data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"ERROR exchanging token: {e}")
        sys.exit(1)

    if token_data.get("access_token"):
        keyring.set_password(
            KEYRING_SERVICE, "access_token", token_data["access_token"]
        )
    if token_data.get("refresh_token"):
        keyring.set_password(
            KEYRING_SERVICE, "refresh_token", token_data["refresh_token"]
        )

    print()
    print("SUCCESS! Tokens stored in Windows Credential Manager.")
    print(f"  access_token: {token_data['access_token'][:10]}...")
    print(f"  refresh_token: {'yes' if token_data.get('refresh_token') else 'no'}")
    print(f"  expires_in: {token_data.get('expires_in', 'unknown')} seconds")
    print()
    print("You can now restart Claude Code — ServiceNow MCP will connect automatically.")


if __name__ == "__main__":
    main()
