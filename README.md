# MCP Servers

A collection of Model Context Protocol (MCP) servers for Claude Code, providing integration with INVISTA's data infrastructure.

## Servers

| Server | Purpose | Tools | Auth Method |
| --- | --- | --- | --- |
| snowflake | Snowflake queries + dbt migration automation | 21 | SSO |
| server | Setup Functions, Lambda, S3, CloudWatch, EventBridge | 19 | AWS SSO |
| dbt | dbt Cloud jobs, runs, and local project tasks | 11 | Windows Auth |
| denodo | Denodo virtual database queries | 7 | Username/Password |
| jira | Jira integration | 8 | OAuth |
| confluence | Confluence (ID project) | 4 | OAuth |
| servicenow | ServiceNow ITSM (native MCP via OAuth proxy) | 14 | OAuth 2.0 (SSO) |
| github | GitHub repositories, PRs, and issues | 26 | Personal Access Token |
| powerbi | Power BI REST API (refresh and metadata access) | 30 | N/A (token extension) |
| hana | SAP HANA table queries via AWS tunnel | 6 | AWS SSO |
| datadog | Datadog observability, logs, traces, monitors, dashboards, incidents | 34 | OAuth 2.0 (browser) |
| eventbus | EventBus integration | 18 | OAuth 2.0 (browser) |

The first set of servers are defined in `mcp.json`. `datadog` and `eventbus` are hosted HTTPS servers that you add once at the user level (see Hosted servers).

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
├── cache/
├── confluent/
├── dbt/
├── denodo/
├── docs/
├── github/
├── hana/
├── jira/
├── powerbi-rest/
├── servicenow/
├── shared-skills/
├── snowflake/
├── sqlserver/
├── .gitignore
├── .mcp.json.example
├── README.md
├── requirements.txt
├── setup_credentials.py
└── SETUP_GUIDE.md
```

## Security

Credentials are stored in Windows Credential Manager and encrypted via DPAPI, tied to your Windows login. Tokens are refreshed automatically through the OAuth flow, and only the necessary secrets are kept in the local environment.

## Audit Logs

Each MCP server logs to `logs/<server>.json` or a central application log, depending on configuration. Logs capture request metadata, timestamps, and success/failure outcomes for operational troubleshooting.

## Notes

- Local config values should be kept outside of source control.
- Hosted services use browser-based login flows and are configured once at the user level.
- For production use, validate the environment-specific endpoints and auth settings before enabling the servers in your workflow.
