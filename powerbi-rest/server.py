#!/usr/bin/env python3
"""
Power BI REST API MCP Server.

Provides Power BI admin tools via the Power BI REST API using
service principal (client credentials) authentication.

Tools: list workspaces, list datasets, refresh history, dataset details,
trigger refresh (full/table/partition), cancel refresh, list partitions,
update refresh schedule, list reports, get data sources, and get capacity info.
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime
from typing import Any

import msal
import requests

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.credentials import get_secret
from shared.audit import audit_tool_call

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOOL_TIMEOUT = int(os.getenv("MCP_TOOL_TIMEOUT", "120"))

POWERBI_API = "https://api.powerbi.com/v1.0/myorg"
POWERBI_SCOPE = ["https://analysis.windows.net/powerbi/api/.default"]

app = Server("powerbi-rest-mcp-server")
_msal_app = None


# ---------------------------------------------------------------------------
# Authentication and REST helpers
# ---------------------------------------------------------------------------

def _get_msal_app():
    global _msal_app
    if _msal_app is None:
        tenant_id = os.environ["POWERBI_TENANT_ID"]
        client_id = os.environ["POWERBI_CLIENT_ID"]
        client_secret = get_secret(
            "mcp-powerbi-rest", "client_secret", "POWERBI_CLIENT_SECRET"
        )
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        _msal_app = msal.ConfidentialClientApplication(
            client_id,
            authority=authority,
            client_credential=client_secret,
        )
    return _msal_app


def get_access_token() -> str:
    msal_app = _get_msal_app()
    result = msal_app.acquire_token_silent(POWERBI_SCOPE, account=None)
    if not result:
        result = msal_app.acquire_token_for_client(scopes=POWERBI_SCOPE)
    if "access_token" not in result:
        error = result.get("error_description", result.get("error", "Unknown error"))
        raise RuntimeError(f"Failed to acquire token: {error}")
    return result["access_token"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {get_access_token()}"}


def api_get(path: str, params: dict | None = None) -> dict:
    resp = requests.get(
        f"{POWERBI_API}{path}", headers=_headers(), params=params, timeout=60
    )
    resp.raise_for_status()
    return resp.json()


def api_post(path: str, body: dict | None = None) -> requests.Response:
    resp = requests.post(
        f"{POWERBI_API}{path}",
        headers={**_headers(), "Content-Type": "application/json"},
        json=body,
        timeout=120,
    )
    resp.raise_for_status()
    return resp


def api_patch(path: str, body: dict) -> requests.Response:
    resp = requests.patch(
        f"{POWERBI_API}{path}",
        headers={**_headers(), "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    resp.raise_for_status()
    return resp


def api_delete(path: str) -> requests.Response:
    resp = requests.delete(f"{POWERBI_API}{path}", headers=_headers(), timeout=60)
    resp.raise_for_status()
    return resp


def resolve_workspace_id(workspace_name: str) -> str:
    data = api_get("/groups", params={"$filter": f"name eq '{workspace_name}'"})
    groups = data.get("value", [])
    if not groups:
        raise ValueError(
            f"Workspace '{workspace_name}' not found. Check the name or service principal access."
        )
    return groups[0]["id"]


def resolve_dataset_id(workspace_id: str, dataset_name: str) -> str:
    data = api_get(f"/groups/{workspace_id}/datasets")
    for ds in data.get("value", []):
        if ds["name"].lower() == dataset_name.lower():
            return ds["id"]
    available = [ds["name"] for ds in data.get("value", [])]
    raise ValueError(
        f"Dataset '{dataset_name}' not found in workspace. "
        f"Available datasets: {', '.join(available[:20])}"
    )


def _fmt_duration(start_str: str, end_str: str) -> str:
    try:
        fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
        start = datetime.strptime(start_str[:26] + "Z", fmt)
        end = datetime.strptime(end_str[:26] + "Z", fmt)
        mins = (end - start).total_seconds() / 60
        return f" ({mins:.1f} min)"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    Tool(
        name="powerbi_list_workspaces",
        description="List Power BI workspaces the service principal has access to.",
        inputSchema={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": "Optional: filter by name substring (case-insensitive)",
                }
            },
        },
    ),
    Tool(
        name="powerbi_list_datasets",
        description="List all datasets (semantic models) in a Power BI workspace.",
        inputSchema={
            "type": "object",
            "properties": {
                "workspace_name": {"type": "string", "description": "Exact workspace name"}
            },
            "required": ["workspace_name"],
        },
    ),
    Tool(
        name="powerbi_get_refresh_history",
        description="Get refresh history for a dataset. Shows start/end times, status, duration, and errors.",
        inputSchema={
            "type": "object",
            "properties": {
                "workspace_name": {"type": "string", "description": "Exact workspace name"},
                "dataset_name": {
                    "type": "string",
                    "description": "Exact dataset/semantic model name",
                },
                "top": {
                    "type": "integer",
                    "description": "Number of entries (default: 10)",
                    "default": 10,
                },
            },
            "required": ["workspace_name", "dataset_name"],
        },
    ),
    Tool(
        name="powerbi_get_dataset_details",
        description="Get dataset details including refresh schedule, timezone, data sources, and whether refreshable.",
        inputSchema={
            "type": "object",
            "properties": {
                "workspace_name": {"type": "string", "description": "Exact workspace name"},
                "dataset_name": {
                    "type": "string",
                    "description": "Exact dataset/semantic model name",
                },
            },
            "required": ["workspace_name", "dataset_name"],
        },
    ),
    Tool(
        name="powerbi_trigger_refresh",
        description=(
            "Trigger a dataset refresh. Supports full refresh, table-level refresh, "
            "partition-level refresh (for historical partitions), or apply refresh policy "
            "(for incremental refresh models). Use powerbi_list_partitions first to get partition names."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "workspace_name": {"type": "string", "description": "Exact workspace name"},
                "dataset_name": {
                    "type": "string",
                    "description": "Exact dataset/semantic model name",
                },
                "refresh_type": {
                    "type": "string",
                    "description": "Type of refresh: 'full' (default), 'dataOnly', 'calculate', 'automatic'",
                    "default": "full",
                    "enum": ["full", "dataOnly", "calculate", "automatic"],
                },
                "objects": {
                    "type": "array",
                    "description": (
                        "Optional specific tables/partitions to refresh. Each item: "
                        '{"table": "TableName"} or {"table": "TableName", "partition": "PartitionName"}. '
                        "If omitted, refreshes the entire dataset."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "table": {"type": "string", "description": "Table name"},
                            "partition": {
                                "type": "string",
                                "description": "Partition name (optional)",
                            },
                        },
                        "required": ["table"],
                    },
                },
                "commit_mode": {
                    "type": "string",
                    "description": "'transactional' (all or nothing, default) or 'partialBatch' (partial success OK)",
                    "default": "transactional",
                    "enum": ["transactional", "partialBatch"],
                },
                "apply_refresh_policy": {
                    "type": "boolean",
                    "description": "If true, applies incremental refresh policy instead of refreshing all partitions. Default: false.",
                    "default": False,
                },
                "effective_date": {
                    "type": "string",
                    "description": "Override 'today' for refresh policy (ISO date, e.g. '2026-01-15'). Only used with apply_refresh_policy.",
                },
            },
            "required": ["workspace_name", "dataset_name"],
        },
    ),
    Tool(
        name="powerbi_cancel_refresh",
        description="Cancel an in-progress dataset refresh.",
        inputSchema={
            "type": "object",
            "properties": {
                "workspace_name": {"type": "string", "description": "Exact workspace name"},
                "dataset_name": {
                    "type": "string",
                    "description": "Exact dataset/semantic model name",
                },
            },
            "required": ["workspace_name", "dataset_name"],
        },
    ),
    Tool(
        name="powerbi_list_partitions",
        description=(
            "List all partitions for a table in a dataset. Use this to find partition names "
            "before triggering a partition-level refresh. Runs a DAX query via the executeQueries REST API."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "workspace_name": {"type": "string", "description": "Exact workspace name"},
                "dataset_name": {
                    "type": "string",
                    "description": "Exact dataset/semantic model name",
                },
                "table_name": {
                    "type": "string",
                    "description": "Optional: filter partitions for a specific table. If omitted, shows all tables.",
                },
            },
            "required": ["workspace_name", "dataset_name"],
        },
    ),
    Tool(
        name="powerbi_update_refresh_schedule",
        description="Update the refresh schedule for a dataset. Can change days, times, timezone, and enable/disable.",
        inputSchema={
            "type": "object",
            "properties": {
                "workspace_name": {"type": "string", "description": "Exact workspace name"},
                "dataset_name": {
                    "type": "string",
                    "description": "Exact dataset/semantic model name",
                },
                "enabled": {
                    "type": "boolean",
                    "description": "Enable or disable scheduled refresh",
                },
                "days": {
                    "type": "array",
                    "description": "Days to refresh, e.g. ['Monday','Tuesday','Wednesday','Thursday','Friday']",
                    "items": {"type": "string"},
                },
                "times": {
                    "type": "array",
                    "description": "Times to refresh in HH:MM format, e.g. ['06:00','18:00']",
                    "items": {"type": "string"},
                },
                "timezone": {
                    "type": "string",
                    "description": "Timezone ID, e.g. 'UTC', 'Central Standard Time', 'India Standard Time'",
                },
                "notify_option": {
                    "type": "string",
                    "description": "'MailOnFailure' or 'NoNotification'",
                    "enum": ["MailOnFailure", "NoNotification"],
                },
            },
            "required": ["workspace_name", "dataset_name"],
        },
    ),
    Tool(
        name="powerbi_list_reports",
        description="List all reports in a Power BI workspace.",
        inputSchema={
            "type": "object",
            "properties": {
                "workspace_name": {"type": "string", "description": "Exact workspace name"}
            },
            "required": ["workspace_name"],
        },
    ),
    Tool(
        name="powerbi_get_datasources",
        description="Get data source connection details for a dataset. Useful for troubleshooting refresh failures.",
        inputSchema={
            "type": "object",
            "properties": {
                "workspace_name": {"type": "string", "description": "Exact workspace name"},
                "dataset_name": {
                    "type": "string",
                    "description": "Exact dataset/semantic model name",
                },
            },
            "required": ["workspace_name", "dataset_name"],
        },
    ),
    Tool(
        name="powerbi_get_capacity_info",
        description=(
            "Get capacity details for a workspace including SKU, state, admins, and capacity ID. "
            "Useful for diagnosing slow refreshes or capacity throttling."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "workspace_name": {"type": "string", "description": "Exact workspace name"}
            },
            "required": ["workspace_name"],
        },
    ),
]


@app.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _handle_list_workspaces(arguments: dict) -> str:
    name_filter = arguments.get("filter", "").lower()
    data = api_get("/groups")
    workspaces = data.get("value", [])
    if name_filter:
        workspaces = [w for w in workspaces if name_filter in w["name"].lower()]
    if not workspaces:
        return "No workspaces found matching the filter."
    lines = [f"Found {len(workspaces)} workspace(s):\n"]
    for w in workspaces:
        lines.append(f" - {w['name']} (id: {w['id']})")
    return "\n".join(lines)


def _handle_list_datasets(arguments: dict) -> str:
    ws_id = resolve_workspace_id(arguments["workspace_name"])
    data = api_get(f"/groups/{ws_id}/datasets")
    datasets = data.get("value", [])
    if not datasets:
        return f"No datasets found in workspace '{arguments['workspace_name']}'."
    lines = [
        f"Found {len(datasets)} dataset(s) in '{arguments['workspace_name']}':\n"
    ]
    for ds in datasets:
        refreshable = "Yes" if ds.get("isRefreshable") else "No"
        lines.append(
            f" - {ds['name']} (refreshable: {refreshable}, id: {ds['id']})"
        )
    return "\n".join(lines)


def _handle_refresh_history(arguments: dict) -> str:
    ws_id = resolve_workspace_id(arguments["workspace_name"])
    ds_id = resolve_dataset_id(ws_id, arguments["dataset_name"])
    top = arguments.get("top", 10)
    data = api_get(
        f"/groups/{ws_id}/datasets/{ds_id}/refreshes", params={"$top": top}
    )
    refreshes = data.get("value", [])
    if not refreshes:
        return f"No refresh history found for '{arguments['dataset_name']}'."
    lines = [
        f"Refresh history for '{arguments['dataset_name']}' "
        f"(last {len(refreshes)} entries):\n"
    ]
    for r in refreshes:
        status = r.get("status", "Unknown")
        refresh_type = r.get("refreshType", "Unknown")
        start = r.get("startTime", "N/A")
        end = r.get("endTime", "N/A")
        duration = _fmt_duration(start, end) if start != "N/A" and end != "N/A" else ""
        lines.append(f"  {start} -> {end}{duration}")
        lines.append(f"    Status: {status} | Type: {refresh_type}")
        if r.get("serviceExceptionJson"):
            lines.append(f"    Error: {r['serviceExceptionJson'][:200]}")
        lines.append("")
    return "\n".join(lines)


def _handle_dataset_details(arguments: dict) -> str:
    ws_id = resolve_workspace_id(arguments["workspace_name"])
    ds_id = resolve_dataset_id(ws_id, arguments["dataset_name"])
    ds_data = api_get(f"/groups/{ws_id}/datasets/{ds_id}")

    lines = [f"Dataset: {ds_data.get('name', arguments['dataset_name'])}\n"]
    lines.append(f"  ID: {ds_data.get('id')}")
    lines.append(f"  Refreshable: {ds_data.get('isRefreshable')}")
    lines.append(f"  Configured By: {ds_data.get('configuredBy', 'N/A')}")
    lines.append(f"  Created: {ds_data.get('createdDate', 'N/A')}")

    try:
        schedule = api_get(f"/groups/{ws_id}/datasets/{ds_id}/refreshSchedule")
        lines.append("\nRefresh Schedule:")
        lines.append(f"  Enabled: {schedule.get('enabled')}")
        lines.append(f"  Frequency: {schedule.get('frequency', 'N/A')}")
        lines.append(f"  Days: {schedule.get('days', [])}")
        lines.append(f"  Times: {schedule.get('times', [])}")
        lines.append(f"  Timezone: {schedule.get('localTimeZoneId', 'N/A')}")
        lines.append(f"  Notify Option: {schedule.get('notifyOption', 'N/A')}")
    except Exception as e:
        lines.append(f"\nRefresh Schedule: Could not retrieve ({e})")

    try:
        sources = api_get(f"/groups/{ws_id}/datasets/{ds_id}/datasources")
        ds_list = sources.get("value", [])
        if ds_list:
            lines.append(f"\nData Sources ({len(ds_list)}):")
            for src in ds_list:
                conn = src.get("connectionDetails", {})
                lines.append(f"  - Type: {src.get('datasourceType', 'N/A')}")
                if conn.get("server"):
                    lines.append(f"    Server: {conn['server']}")
                if conn.get("database"):
                    lines.append(f"    Database: {conn['database']}")
    except Exception as e:
        lines.append(f"\nData Sources: Could not retrieve ({e})")
    return "\n".join(lines)


def _handle_trigger_refresh(arguments: dict) -> str:
    ws_id = resolve_workspace_id(arguments["workspace_name"])
    ds_id = resolve_dataset_id(ws_id, arguments["dataset_name"])

    body: dict[str, Any] = {
        "type": arguments.get("refresh_type", "full"),
        "commitMode": arguments.get("commit_mode", "transactional"),
    }
    if arguments.get("objects"):
        body["objects"] = arguments["objects"]
    if arguments.get("apply_refresh_policy"):
        body["applyRefreshPolicy"] = True
        if arguments.get("effective_date"):
            body["effectiveDate"] = arguments["effective_date"]

    resp = api_post(f"/groups/{ws_id}/datasets/{ds_id}/refreshes", body)
    request_id = resp.headers.get("x-ms-request-id", "N/A")

    desc = "full dataset"
    if arguments.get("objects"):
        parts = []
        for obj in arguments["objects"]:
            if obj.get("partition"):
                parts.append(f"{obj['table']}/{obj['partition']}")
            else:
                parts.append(obj["table"])
        desc = ", ".join(parts)
    elif arguments.get("apply_refresh_policy"):
        desc = "incremental refresh policy"

    return (
        f"Refresh triggered successfully for '{arguments['dataset_name']}'.\n"
        f"  Scope: {desc}\n"
        f"  Type: {body['type']}\n"
        f"  Commit Mode: {body['commitMode']}\n"
        f"  Request ID: {request_id}\n\n"
        "Use powerbi_get_refresh_history to monitor progress."
    )


def _handle_cancel_refresh(arguments: dict) -> str:
    ws_id = resolve_workspace_id(arguments["workspace_name"])
    ds_id = resolve_dataset_id(ws_id, arguments["dataset_name"])
    data = api_get(
        f"/groups/{ws_id}/datasets/{ds_id}/refreshes", params={"$top": 1}
    )
    refreshes = data.get("value", [])
    if not refreshes:
        return "No refresh found to cancel."

    latest = refreshes[0]
    if latest.get("status") != "Unknown":
        return (
            "No in-progress refresh to cancel. "
            f"Latest refresh status: {latest.get('status')}"
        )
    request_id = latest.get("requestId")
    if not request_id:
        return "Could not find request ID for the in-progress refresh."

    api_delete(f"/groups/{ws_id}/datasets/{ds_id}/refreshes/{request_id}")
    return f"Refresh cancelled successfully.\nRequest ID: {request_id}"


def _handle_list_partitions(arguments: dict) -> str:
    ws_id = resolve_workspace_id(arguments["workspace_name"])
    ds_id = resolve_dataset_id(ws_id, arguments["dataset_name"])

    dax = (
        "EVALUATE SELECTCOLUMNS("
        "INFO.PARTITIONS(), "
        '"TableName", [TableName], '
        '"PartitionName", [Name], '
        '"Mode", [Mode], '
        '"State", [State], '
        '"RecordCount", [RecordCount], '
        '"ModifiedTime", [ModifiedTime]'
        ")"
    )
    table_filter = arguments.get("table_name")
    body = {"queries": [{"query": dax}], "serializerSettings": {"includeNulls": True}}
    resp = api_post(f"/groups/{ws_id}/datasets/{ds_id}/executeQueries", body)
    result = resp.json()

    rows = []
    for table in result.get("results", []):
        for row in table.get("tables", [{}])[0].get("rows", []):
            tname = row.get("[TableName]", "")
            if table_filter and tname.lower() != table_filter.lower():
                continue
            rows.append(row)

    if not rows:
        suffix = f" for table '{table_filter}'" if table_filter else ""
        return f"No partitions found{suffix}."

    current_table = None
    lines = [f"Partitions for '{arguments['dataset_name']}'"]
    if table_filter:
        lines[0] += f" (table: {table_filter})"
    lines.append("")
    rows.sort(key=lambda r: (r.get("[TableName]", ""), r.get("[PartitionName]", "")))

    for row in rows:
        tname = row.get("[TableName]", "")
        if tname != current_table:
            current_table = tname
            lines.append(f"[{tname}]")
        pname = row.get("[PartitionName]", "")
        mode = row.get("[Mode]", "")
        records = row.get("[RecordCount]", "")
        modified = row.get("[ModifiedTime]", "")
        record_str = (
            f", {records:,} rows"
            if isinstance(records, (int, float)) and records > 0
            else ""
        )
        lines.append(f"  {pname} (mode: {mode}{record_str})")
        if modified:
            lines.append(f"    Modified: {modified}")
    return "\n".join(lines)


def _handle_update_refresh_schedule(arguments: dict) -> str:
    ws_id = resolve_workspace_id(arguments["workspace_name"])
    ds_id = resolve_dataset_id(ws_id, arguments["dataset_name"])

    schedule_body: dict[str, Any] = {"value": {}}
    val = schedule_body["value"]
    if "enabled" in arguments:
        val["enabled"] = arguments["enabled"]
    if "days" in arguments:
        val["days"] = arguments["days"]
    if "times" in arguments:
        val["times"] = arguments["times"]
    if "timezone" in arguments:
        val["localTimeZoneId"] = arguments["timezone"]
    if "notify_option" in arguments:
        val["notifyOption"] = arguments["notify_option"]

    if not val:
        return (
            "No schedule changes specified. Provide at least one of: "
            "enabled, days, times, timezone, notify_option."
        )

    api_patch(f"/groups/{ws_id}/datasets/{ds_id}/refreshSchedule", schedule_body)
    changes = [f"  {k}: {v}" for k, v in val.items()]
    return (
        f"Refresh schedule updated for '{arguments['dataset_name']}'.\n"
        "Changes applied:\n" + "\n".join(changes)
    )


def _handle_list_reports(arguments: dict) -> str:
    ws_id = resolve_workspace_id(arguments["workspace_name"])
    data = api_get(f"/groups/{ws_id}/reports")
    reports = data.get("value", [])
    if not reports:
        return f"No reports found in workspace '{arguments['workspace_name']}'."
    lines = [f"Found {len(reports)} report(s) in '{arguments['workspace_name']}':\n"]
    for report in reports:
        ds_id = report.get("datasetId", "N/A")
        lines.append(f"  - {report['name']}")
        lines.append(f"    Dataset ID: {ds_id}")
        if report.get("webUrl"):
            lines.append(f"    URL: {report['webUrl']}")
        lines.append("")
    return "\n".join(lines)


def _handle_get_datasources(arguments: dict) -> str:
    ws_id = resolve_workspace_id(arguments["workspace_name"])
    ds_id = resolve_dataset_id(ws_id, arguments["dataset_name"])
    data = api_get(f"/groups/{ws_id}/datasets/{ds_id}/datasources")
    sources = data.get("value", [])
    if not sources:
        return f"No data sources found for '{arguments['dataset_name']}'."

    lines = [
        f"Data sources for '{arguments['dataset_name']}' ({len(sources)}):\n"
    ]
    for i, src in enumerate(sources, 1):
        conn = src.get("connectionDetails", {})
        gateway_id = src.get("gatewayId", "N/A")
        lines.append(f"  Source {i}:")
        lines.append(f"    Type: {src.get('datasourceType', 'N/A')}")
        lines.append(f"    Datasource ID: {src.get('datasourceId', 'N/A')}")
        lines.append(f"    Gateway ID: {gateway_id}")
        if conn.get("server"):
            lines.append(f"    Server: {conn['server']}")
        if conn.get("database"):
            lines.append(f"    Database: {conn['database']}")
        if conn.get("url"):
            lines.append(f"    URL: {conn['url']}")
        if conn.get("path"):
            lines.append(f"    Path: {conn['path']}")
        lines.append("")
    return "\n".join(lines)


def _handle_get_capacity_info(arguments: dict) -> str:
    ws_name = arguments["workspace_name"]
    resolve_workspace_id(ws_name)
    group_data = api_get("/groups", params={"$filter": f"name eq '{ws_name}'"})
    group = group_data.get("value", [{}])[0]
    capacity_id = group.get("capacityId")

    if not capacity_id:
        return (
            f"Workspace '{ws_name}' is not assigned to a dedicated capacity "
            "(likely shared/Pro)."
        )

    try:
        cap = api_get(f"/capacities/{capacity_id}")
    except requests.HTTPError:
        cap = None

    if not cap:
        try:
            caps_data = api_get("/capacities")
            for capacity in caps_data.get("value", []):
                if capacity.get("id") == capacity_id:
                    cap = capacity
                    break
        except requests.HTTPError:
            pass

    lines = [f"Capacity info for workspace '{ws_name}':\n"]
    lines.append(f"  Capacity ID: {capacity_id}")
    if cap:
        lines.append(f"  Display Name: {cap.get('displayName', 'N/A')}")
        lines.append(f"  SKU: {cap.get('sku', 'N/A')}")
        lines.append(f"  State: {cap.get('state', 'N/A')}")
        lines.append(f"  Region: {cap.get('region', 'N/A')}")
        admins = cap.get("admins", [])
        if admins:
            lines.append(f"  Admins: {', '.join(admins)}")
        tenants = cap.get("tenantKeyId", "N/A")
        lines.append(f"  Tenant Key ID: {tenants}")
    else:
        lines.append(
            "  (Could not retrieve full capacity details - service principal may need "
            "Capacity.Read.All permission)"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

HANDLERS = {
    "powerbi_list_workspaces": _handle_list_workspaces,
    "powerbi_list_datasets": _handle_list_datasets,
    "powerbi_get_refresh_history": _handle_refresh_history,
    "powerbi_get_dataset_details": _handle_dataset_details,
    "powerbi_trigger_refresh": _handle_trigger_refresh,
    "powerbi_cancel_refresh": _handle_cancel_refresh,
    "powerbi_list_partitions": _handle_list_partitions,
    "powerbi_update_refresh_schedule": _handle_update_refresh_schedule,
    "powerbi_list_reports": _handle_list_reports,
    "powerbi_get_datasources": _handle_get_datasources,
    "powerbi_get_capacity_info": _handle_get_capacity_info,
}


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    with audit_tool_call("powerbi-rest", name, arguments) as audit:
        try:
            handler = HANDLERS.get(name)
            if not handler:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            result = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, handler, arguments),
                timeout=TOOL_TIMEOUT,
            )
            return [TextContent(type="text", text=result)]

        except asyncio.TimeoutError:
            return [
                TextContent(
                    type="text",
                    text=f"Tool '{name}' timed out after {TOOL_TIMEOUT}s",
                )
            ]
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "N/A"
            body = ""
            if e.response is not None:
                try:
                    body = e.response.json().get("error", {}).get(
                        "message", e.response.text[:500]
                    )
                except Exception:
                    body = e.response.text[:500]
            return [
                TextContent(
                    type="text",
                    text=f"Power BI API error (HTTP {status}): {body}",
                )
            ]
        except Exception as e:
            logger.exception("Tool '%s' failed", name)
            return [TextContent(type="text", text=f"Error: {type(e).__name__}: {e}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream, write_stream, app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
