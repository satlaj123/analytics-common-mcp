# MCP Servers

A collection of Model Context Protocol (MCP) servers for Claude Code, providing integration with INVISTA's data infrastructure.

## Servers

| Server | Purpose | Tools | Auth Method |
| --- | --- | --- | --- |
| aws | AWS setup utilities and Lambda/S3/CloudWatch integrations | 19 | AWS SSO |
| snowflake | Snowflake queries and setup helpers | 21 | SSO |
| sqlserver | SQL Server database access | 10 | Windows/Auth |
| denodo | Denodo virtual database queries | 7 | Username/Password |
| jira | Jira integration | 8 | OAuth |
| confluence | Confluence integration | 4 | OAuth |
| dbt | dbt Cloud jobs, runs, and local project tasks | 11 | Token |
| servicenow | ServiceNow ITSM and OAuth proxy | 14 | OAuth 2.0 |
| github | GitHub repositories, PRs, and issues | 26 | Personal Access Token |
| powerbi-rest | Power BI REST API support | 30 | Token-based |
| hana | SAP HANA queries via tunnel | 6 | AWS SSO |

These servers are configured in `.mcp.json` and local helper scripts during setup.

## Setup

### Prerequisites

- Python 3.10+ with a virtual environment
- Node.js (for GitHub MCP) environment
- AWS CLI v2 with SSO configured
- ODBC Driver for SQL Server

### Quick Start

1. Clone this repo.
2. Create a virtual environment and install dependencies:

```bash
python -m venv .venv
# Windows
.\venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
pip install -r requirements.txt
```

3. Store credentials in Windows Credential Manager:

```bash
python setup_credentials.py
```

4. Authenticate with ServiceNow (one-time browser login):

```bash
python servicenow/setup_auth.py
```

5. Copy the example MCP config and update the values to match your environment:

```bash
cp .mcp.json.example .mcp.json
```

6. Start the servers you need using your local Claude Code or MCP client configuration.

## Credential Management

Secrets are stored in Windows Credential Manager (encrypted, tied to your Windows login) and not in config files.

```bash
python setup_credentials.py
python setup_credentials.py --list
python setup_credentials.py --verify
python setup_credentials.py --set KEY "value"
python setup_credentials.py --update KEY "new value"
```

Stored credentials:

| Key | Service | Description |
| --- | --- | --- |
| mcp-atlassian/client_secret | Jira / Confluence | Atlassian OAuth client secret |
| mcp-denodo/password | Denodo | Denodo login password |
| mcp-dbt/api_token | dbt | dbt Cloud API token |
| mcp-servicenow/client_id | ServiceNow | OAuth client ID |
| mcp-servicenow/client_secret | ServiceNow | OAuth client secret |
| mcp-servicenow/access_token | ServiceNow | OAuth access token |
| mcp-servicenow/refresh_token | ServiceNow | OAuth refresh token |
| mcp-powerbi/* | Power BI | REST API access and token management |

## Hosted Servers: Datadog and EventBus

These two servers run on hosted services, so they are not in `.mcp.json`. You add each one once at the user level.

```bash
claude mcp add --transport http --scope user Datadog https://.../datadog
claude mcp add --transport http --scope user EventBus https://.../eventbus
```

The setup is done through a browser-based OAuth flow. Once added, the access token is refreshed automatically and you do not need to keep re-authenticating.

## ServiceNow Setup

First-time setup (opens browser for SSO login):

```bash
python servicenow/setup_auth.py
```

Token auto-refreshes on subsequent restarts — no browser needed.

```bash
# Example environment variables
# Dev: https://<dev-instance>/api/now/table
# Prod: https://<prod-instance>/api/now/table
```

When switching environments, change `SERVICENOW_MCP_URL` in your local config or `.mcp.json` before restarting the MCP server.

## Dependencies

```bash
pip install mcp botocore snowflake-connector-python python-dotenv pyyaml requests sqlalchemy
```

Optional packages used by the project may include the SQL Server ODBC client and AWS tooling as required by your deployment environment.

## Structure

```text
analytics-common-mcp/
├── aws/
│   └── run_server.py
├── confluence/
│   └── confluence_server.py
├── dbt/
│   └── dbt_server.py
├── denodo/
│   └── denodo_server.py
├── github/
│   ├── run-github-mcp.cmd
│   └── github-mcp.cmd
├── hana/
│   └── hana_server.py
├── jira/
│   └── jira_server.py
├── logs/
├── powerbi-rest/
│   └── server.py
├── servicenow/
│   ├── servicenow_proxy.py
│   └── setup_auth.py
├── shared/
│   ├── credentials.py
│   ├── audit.py
│   └── logs/
├── snowflake/
│   └── server.py
├── sqlserver/
│   └── sqlserver_server.py
├── .env.example
├── .gitignore
├── .mcp.json.example
├── README.md
├── requirements.txt
├── setup_credentials.py
└── SETUP_GUIDE.md
```

## Security

- Credentials are stored in Windows Credential Manager and encrypted via DPAPI, tied to your Windows login.
- No secrets are kept in config files — `.mcp.json` contains only URLs, hostnames, and account IDs.
- Audit logging records every tool call to `logs/<server>.json` with timestamp, user, server, tool name, arguments (passwords masked), status, and duration.
- Log retention is 15 days; old entries are auto-pruned on server startup.
- Snowflake, SQL Server, Denodo, and HANA are read-only by default and block write operations.
- ServiceNow, AWS, and Snowflake rely on user-level SSO access instead of service accounts or privilege escalation.
- ServiceNow MCP respects ACLs and only exposes data a user can access.
- `.env` and `.mcp.json` are gitignored and never committed.

## Audit Logs

Each MCP server logs to `logs/<server>.json`:

```json
{
  "timestamp": "2026-09-02T10:18:27Z",
  "user": "mmanis7",
  "server": "servicenow",
  "tool": "query incident",
  "arguments": { "sys_id": "..." },
  "status": "success",
  "duration_ms": 321
}
```

Logged fields include timestamp, user, server, tool name, arguments (with passwords masked), status, and duration. Response data, PII, and query results are not logged.

## Notes

- Local config values should be kept outside of source control.
- Hosted services use browser-based login flows and are configured once at the user level.
- For production use, validate the environment-specific endpoints and auth settings before enabling the servers in your workflow.
