# SETUP GUIDE - MCP Servers

Step-by-step instructions for setting up the MCP servers (the local servers in `.mcp.json`, plus the two hosted servers, Datadog and EventBus, in Step 2.10). Total time: ~30 minutes.

## Prerequisites

- **Python 3.10+** — verify: `python --version` or `py --version`
- **Node.js** — for GitHub MCP (check: `node --version`)
- **AWS CLI v2** — for AWS MCP (check: `aws --version`)
- **ODBC Driver for SQL Server** — for SQL Server MCP
- **Claude Code** — VS Code extension with MCP support
- **VPN** — recommended to access the INVISTA network (for Snowflake, Denodo)

## Step 1: Clone and Install

```bash
# bash
git clone https://github.com/invista/mcp-servers.git
cd mcp-servers
```

### Create virtual environment

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
```

### Install all dependencies

```bash
pip install -r requirements.txt
```

## Step 2: Generate Credentials

### 2.1 - GitHub Personal Access Token

1. Go to https://github.com/settings/tokens
2. Click **Generate new token (classic)**
3. Give it a name (e.g., "Claude Code MCP")
4. Select scopes:
   - `repo` (full)
   - `read:org`
   - `read:project`
5. Click **Generate token**
6. Copy the token (starts with `ghp_`)

### 2.2 - AWS SSO Profiles

1. Open `~/.aws/config` (create if needed) and add your profiles:

```ini
[ss-sesion claude]
sso_start_url = https://d-96b...awsapps.com/start/
sso_region = us-east-2
sso_registration_scopes = sso:account:access

[profile inv-analytics-micro-prod]
sso_session = claude
sso_account_id = <YOUR_ACCOUNT_ID>
sso_role_name = InvBuilder
region = us-east-2

[profile inv-analytics-micro-dev]
sso_session = claude
sso_account_id = <YOUR_ACCOUNT_ID>
sso_role_name = InvBuilder
region = us-east-2
```

2. Find your account ID and role name:
   - Open `~/.aws/config` file or use `aws sts get-caller-identity`
   - Expand each account to see available roles
3. Authenticate:

```bash
aws sso login --profile inv-analytics-micro-prod
```

4. Use `aws --profile` or set default profile as needed

### 2.3 - Atlassian (Jira & Confluence) OAuth App

Both Jira and Confluence share the same OAuth app credentials.

**Get the Cloud ID:**

1. Go to https://admin.atlassian.com
2. Select your organization and your Jira/Confluence site
3. Go to **Products** -> **Sites** -> select your site
4. The Cloud ID is in the URL, or use:

```bash
https://<instance>.atlassian.net/edge/tenant_info
```

Look for the `cloudId` field in the JSON response.

**Get OAuth credentials** (ask your team lead — these are shared):

- The `CLIENT_ID` and `CLIENT_SECRET` come from an Atlassian OAuth 2.0 app
- If you need to create a new app:
  1. Go to https://developer.atlassian.com/console/myapps/
  2. Click **Create** -> **OAuth 2.0 integration**
  3. Name it (e.g., "Claude Code MCP")
  4. Under **Authorization** -> add callback URL: `http://localhost:8000/callback`
  5. Under **API permissions** add:
     - `read:jira-user`
     - `write:jira-work`
     - `read:confluence`
     - `write:confluence`
     - `search:confluence`
     - `write:page`
  6. Under **Settings** -> copy the **Client ID** and **Client Secret**

**First-time authorization (generates tokens):**

```bash
# bash
# Set env vars first
set ATLASSIAN_CLIENT_ID=<your_client_id>
set ATLASSIAN_CLIENT_SECRET=<your_client_secret>

# Run the auth flow
python confluence/confluence_auth.py
```

Browser opens -> log in -> authorize -> tokens are saved to `confluence_tokens.json`.
Copy the token file for Jira too:

```bash
# bash
copy confluence\confluence_tokens.json jira\jira_tokens.json
```

### 2.4 - Denodo

Uses your Koch/INVISTA domain credentials (same as VDI login):

- **Host:** `invawsden01.dtnet.net`
- **Username:** `<yourname>@koch.com`
- **Password:** `your Koch password`

### 2.5 - dbt Cloud

1. Log in to dbt Cloud: https://<org>.us1.dbt.com
2. Click your profile (bottom left) -> **Account Settings**
3. Note your Account ID (in the URL: `/accounts/<id>/...`)
4. Go to **API Access** -> **Generate New Token**
5. Create a token with permissions: `Job Admin`, `Metadata Access`, `Project Admin`
6. Copy the token

### 2.6 - SQL Server

**No credentials needed** — uses Windows Authentication automatically.

- Must be on INVISTA network (VPN if needed)
- Your KOCH\username domain login is used
- Server: `invawsdb01`

**Verify ODBC driver:**

```bash
python
import pyodbc; print([d for d in pyodbc.drivers() if 'SQL' in d])
```

You need either **ODBC Driver 17 for SQL Server** or **SQL Server**. If missing, download from Microsoft.

### 2.7 - Snowflake

Uses browser-based SSO (externalbrowser) — no password needed:

- **Account:** `check with your team (format: "xxxyy-uest-2.aws")`
- **User:** `your.name@koch.com`
- First login will open a browser for Okta SSO login

### 2.8 - ServiceNow

Currently requires a service account or OAuth client credentials. Ask the team lead for:

- Client ID and Client Secret
- Instance URL (for example: `https://<instance>.service-now.com`)

## Step 3: Create `.env` File

```bash
# bash
copy env.example .env
```

Edit `.env` with your actual values from Step 2.

## Step 4: Create `.mcp.json`

```bash
# bash
copy .mcp.json.example .mcp.json
```

Edit `.mcp.json`:

1. Update all `C:\path\to\...` with your actual paths
2. Fill in env var values for each server
3. Remove any servers you don't need

## Step 5: Reload and Test

1. Reload VS Code: `Ctrl+Shift+P` -> **Reload Window**
2. Check MCP status: type `/mcp` in Claude Code
3. Test each server:
   - `List SSO buckets` (AWS)
   - `List databases on SQL Server` (SQL Server)
   - `List pipelines` (AWS Step Functions)
   - `Query Snowflake: SELECT CURRENT_USER()` (Snowflake)
   - `List data sources` (Denodo)
   - `List Jira issues` (Jira)
   - `List Confluence pages` (Confluence)
   - `List GitHub PRs` (GitHub)
4. If needed, restart Claude Code or VS Code

## Troubleshooting

- Issue | Fix
- --- | ---
- AWS `session expired` | Run `aws sso login --profile inv-analytics-micro-prod`
- SQL Server `connection refused` | Check VPN
- Jira/Confluence `unauthorized` | Re-run `python confluence/confluence_auth.py`
- Denodo timeout | Check VPN and verify host is reachable
- MCP server failed to start | Check `.mcp.json`, environment variables, and Python virtual environment
- Datadog tools missing or denied | Ask your Datadog admin to enable MCP access and give your role `mcp_read` (and `mcp_write` if needed)
- Moduled not found | Activate venv and run `pip install -r requirements.txt`

## Token Refresh Schedule

| Server | Token Lifetime | How to Refresh |
| --- | --- | --- |
| AWS SSO | 8-12 hours | `aws sso login --profile inv-analytics-micro-prod` |
| Atlassian OAuth 2.0 | Auto-refresh via refresh token | Re-run `python confluence/confluence_auth.py` when expired |
| GitHub PAT | Until revoked | Regenerate at github.com/settings/tokens |
| dbt Cloud | Until revoked | Regenerate in dbt Cloud account settings |
| Denodo | Session-based | Re-login or re-authenticate |
| ServiceNow | N/A (OAuth) | Re-authenticate via client credentials |
| Snowflake | SSO session | Browser popup on expiry |

## 2.9 - Datadog and EventBus (hosted servers)

These two servers are hosted, so they are added at the user level and not in `.mcp.json`.

**Datadog**

1. Prerequisites: a Datadog account on a supported site. Your Datadog admin must enable `MCP Access` (in Organization Settings -> MCP Access) and give your role `mcp_read` (and `mcp_write` if needed).
2. Get the endpoint for your site from https://docs.datadoghq.com/bits/all/mcp_server/setup/. Use the `/v1/mcp` endpoint, not the deprecated `/api/mcp` path. The page does not include the full URL or token; verify the path from the site docs.
3. Add it:

```bash
claude mcp add --transport http --scope user Datadog <https://.../datadog>
```

4. In Claude Code run `/mcp`, choose `Datadog_official`, and sign in through the browser. Avoid the API-key and token options.
5. Optional: `?toolsets=` and `?omit_tools=` on the endpoint let you leave out the write tools.

**EventBus**

1. Make sure your machine can reach `api.ditnet.net`, and ask the EventBus owner which access or role you need.
2. Add it:

```bash
claude mcp add --transport http --scope user EventBus https://api.ditnet.net/eventbus-mcp/mcp
```

3. In Claude Code run `/mcp`, choose `EventBus`, and sign in through the browser. Every EventBus call needs an `environment` (dev, `nonprod`, or `prod`).

## 2.10 - Hosted server setup summary

- Add each hosted server once at the user level; do not put them in project `.mcp.json`
- Use one shared OAuth or SSO login for AWS, Atlassian, and Datadog where possible
- Re-run `/mcp` after login changes or when tokens expire
- If a hosted server is not listed, reload the app or restart Claude Code

## Final Notes

- Keep secrets in `.env` only for local development and never commit them
- Use the project- or user-level config that matches your environment
- Validate each tool after setup before using it in production flows
