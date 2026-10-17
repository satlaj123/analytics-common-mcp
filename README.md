# MCP Servers

A collection of Model Context Protocol (MCP) servers for Claude Code, providing integration with INVISTA's data infrastructure.

## Repository structure

This repo groups common MCP integrations and shared utilities by domain.

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
├── README.md
├── .gitignore
├── .mcp.json.example
├── requirements.txt
└── setup_credentials.py
```

## Available server areas

- aws — AWS connectivity and operational tooling
- cache — caching and in-memory integration helpers
- confluent — Kafka and event streaming access
- dbt — dbt metadata and job automation
- denodo — virtual data layer access
- docs — project and operational documentation
- github — repo, PR, issue, and workflow tooling
- hana — SAP HANA query access
- jira — issue tracking integration
- powerbi-rest — Power BI refresh and metadata APIs
- servicenow — ITSM and service automation
- shared-skills — reusable prompts and patterns
- snowflake — warehouse and data engineering access
- sqlserver — SQL Server connection and query support

## Quick start

```bash
python -m venv .venv
# Windows
.\venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
pip install -r requirements.txt
```

Then copy the example config and update it for your environment:

```bash
copy .mcp.json.example .mcp.json
```

## Notes

- Keep local credentials and environment-specific values outside source control.
- Use the service folders as the starting point for MCP implementations and shared tooling.
- Extend each server area with focused README files and implementation modules as needed.
