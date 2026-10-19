"""
dbt MCP Server - dbt Cloud API access and local dbt Core CLI execution.

"""

import json
import os
import sys
import asyncio
import subprocess
import urllib.request
import urllib.error
import urllib.parse
import ssl
import importlib.util
from pathlib import Path

from mcp.server import Server
from mcp.types import Tool, TextContent
from dotenv import load_dotenv
from shared.audit import audit_tool_call

load_dotenv()

app = Server("dbt-mcp")

# ---------------------------------------------------------------------------
# dbt Cloud settings
# ---------------------------------------------------------------------------
DBT_CLOUD_ACCOUNT_ID = os.environ.get("DBT_CLOUD_ACCOUNT_ID", "")
DBT_CLOUD_API_TOKEN = os.environ.get("DBT_CLOUD_API_TOKEN", "")
DBT_CLOUD_BASE_URL = os.environ.get(
    "DBT_CLOUD_BASE_URL", "https://z393.us1.dbt.com"
)

# ---------------------------------------------------------------------------
# dbt Core settings
# ---------------------------------------------------------------------------
DBT_PROJECT_ROOT = os.environ.get("DBT_PROJECT_ROOT", "")
UI_PROJECT_ROOT = os.environ.get("UI_PROJECT_ROOT", "")
DBT_EXECUTABLE = os.environ.get("DBT_EXECUTABLE", "dbt")
DBT_PROFILES_DIR = os.environ.get("DBT_PROFILES_DIR", "")
DBT_COMPILE_TIMEOUT = int(os.environ.get("DBT_COMPILE_TIMEOUT", "180"))
DBT_RUN_TIMEOUT = int(os.environ.get("DBT_RUN_TIMEOUT", "300"))

_ssl_ctx = ssl.create_default_context()

# ---------------------------------------------------------------------------
# dbt Cloud API helpers
# ---------------------------------------------------------------------------

def _dbt_cloud_request(method, path, body=None, timeout=60):
    if not DBT_CLOUD_ACCOUNT_ID or not DBT_CLOUD_API_TOKEN:
        return {
            "error": True,
            "details": {
                "message": "dbt Cloud not configured. Set DBT_CLOUD_ACCOUNT_ID and DBT_CLOUD_API_TOKEN in .env"
            },
        }

    url = (
        f"{DBT_CLOUD_BASE_URL}/api/v2/accounts/"
        f"{DBT_CLOUD_ACCOUNT_ID}/{path}"
    )
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Token {DBT_CLOUD_API_TOKEN}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(
            req, context=_ssl_ctx, timeout=timeout
        ) as resp:
            raw = resp.read().decode()
            if not raw:
                return {"status": "success", "code": resp.status}
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        try:
            error_json = json.loads(error_body)
        except (json.JSONDecodeError, ValueError):
            error_json = {"message": error_body}
        return {
            "error": True,
            "status": e.code,
            "details": error_json,
        }
    except urllib.error.URLError as e:
        return {
            "error": True,
            "details": {"message": str(e.reason)},
        }
    except Exception as e:
        return {
            "error": True,
            "details": {"message": str(e)},
        }


# ---------------------------------------------------------------------------
# dbt Core CLI helpers
# ---------------------------------------------------------------------------

def _resolve_project_root(project="common"):
    if project == "ui":
        root = UI_PROJECT_ROOT
        if not root:
            raise ValueError("UI_PROJECT_ROOT not configured in .env")
    else:
        root = DBT_PROJECT_ROOT
        if not root:
            raise ValueError("DBT_PROJECT_ROOT not configured in .env")

    if not Path(root).is_dir():
        raise ValueError(f"Project directory does not exist: {root}")
    return root


def _run_dbt_command(args, project_root, timeout):
    env = os.environ.copy()
    if DBT_PROFILES_DIR:
        env["DBT_PROFILES_DIR"] = DBT_PROFILES_DIR

    cmd = [DBT_EXECUTABLE] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=timeout,
            env=env,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "command": " ".join(cmd),
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"dbt command timed out after {timeout}s",
            "command": " ".join(cmd),
        }
    except FileNotFoundError:
        return {
            "success": False,
            "error": f"dbt executable not found at '{DBT_EXECUTABLE}'. Set DBT_EXECUTABLE in .env.",
        }


def _parse_manifest(project_root):
    manifest_path = Path(project_root) / "target" / "manifest.json"
    if not manifest_path.exists():
        return None
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _get_lineage(model_name, project_root, depth=3):
    manifest = _parse_manifest(project_root)
    if not manifest:
        compile_result = _run_dbt_command(["parse"], project_root, timeout=120)
        if not compile_result.get("success"):
            return {
                "error": "No manifest.json found and dbt parse failed",
                "details": compile_result,
            }
        manifest = _parse_manifest(project_root)

    if not manifest:
        return {"error": "manifest.json still not found after dbt parse"}

    node_key = None
    for key in manifest.get("nodes", {}):
        if key.endswith(f".{model_name}") or manifest["nodes"][key].get("name") == model_name:
            node_key = key
            break

    if not node_key:
        return {"error": f"Model '{model_name}' not found in manifest"}

    parent_map = manifest.get("parent_map", {})
    child_map = manifest.get("child_map", {})

    def walk(graph_map, key, remaining):
        if remaining <= 0:
            return []
        neighbors = graph_map.get(key, [])
        result = []
        for n in neighbors:
            result.append({"node": n, "depth": remaining})
            result.extend(walk(graph_map, n, remaining - 1))
        return result

    return {
        "model": node_key,
        "upstream": walk(parent_map, node_key, depth),
        "downstream": walk(child_map, node_key, depth),
    }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

@app.list_tools()
async def list_tools():
    tools = []

    # dbt Cloud tools (always registered, will error gracefully if not configured)
    tools.extend([
        Tool(
            name="dbt_cloud_list_jobs",
            description="List all dbt Cloud jobs in the account. Shows job names, IDs, schedules, and project associations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "integer",
                        "description": "Optional: filter jobs by project ID",
                    }
                },
                "required": [],
            },
        ),
        Tool(
            name="dbt_cloud_trigger_job",
            description="Trigger a dbt Cloud job run. Returns the run ID for status tracking.",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "integer",
                        "description": "dbt Cloud job ID to trigger",
                    },
                    "cause": {
                        "type": "string",
                        "description": "Description of why this run is triggered",
                    },
                    "git_sha": {
                        "type": "string",
                        "description": "Optional git SHA to run against",
                    },
                },
                "required": ["job_id", "cause"],
            },
        ),
        Tool(
            name="dbt_cloud_run_status",
            description="Check the status of a dbt Cloud run. Returns status, duration, step results, and any errors.",
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer", "description": "dbt Cloud run ID"},
                },
                "required": ["run_id"],
            },
        ),
        Tool(
            name="dbt_cloud_list_runs",
            description="List recent dbt Cloud runs with status. Useful for monitoring job health.",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "integer", "description": "Optional: filter by job ID"},
                    "status": {
                        "type": "string",
                        "enum": ["queued", "starting", "running", "success", "error", "cancelled"],
                        "description": "Optional: filter by run status",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "description": "Max runs to return (default 10)",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="dbt_cloud_get_artifact",
            description="Download artifacts (manifest, run_results, catalog) from a completed dbt Cloud run.",
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer", "description": "dbt Cloud run ID"},
                    "artifact": {
                        "type": "string",
                        "enum": ["manifest.json", "run_results.json", "catalog.json"],
                        "description": "Which artifact to download",
                    },
                },
                "required": ["run_id", "artifact"],
            },
        ),
        Tool(
            name="dbt_cloud_get_latest_artifacts",
            description="Finds the latest successful run of a job — no need to look up run IDs. Finds the latest success and downloads the requested artifact.",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "integer", "description": "dbt Cloud job ID"},
                    "artifact": {
                        "type": "string",
                        "enum": ["manifest.json", "run_results.json", "catalog.json"],
                        "description": "Which artifact to download",
                    },
                },
                "required": ["job_id", "artifact"],
            },
        ),
        Tool(
            name="dbt_cloud_get_environment",
            description="Get details about dbt Cloud environments (deployment targets, credentials, settings).",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "Project ID to list environments for"},
                },
                "required": ["project_id"],
            },
        ),
        Tool(
            name="dbt_cloud_list_runs",
            description="List recent successful artifacts from a job. Finds the latest success and downloads artifacts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "integer", "description": "dbt Cloud job ID"},
                },
                "required": ["job_id"],
            },
        ),
    ])

    # dbt Core tools (local CLI)
    tools.extend([
        Tool(
            name="dbt_compile",
            description="Compile dbt models to validate Jinja templates and ref() resolution without executing against Snowflake. Returns compiled SQL.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "enum": ["common", "ui"],
                        "default": "common",
                        "description": "Which dbt project to use",
                    },
                    "full_refresh": {
                        "type": "boolean",
                        "default": False,
                        "description": "Include --full-refresh flag",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="dbt_run",
            description="Execute dbt model(s) against Snowflake. Use with caution — confirm target is not production.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "enum": ["common", "ui"],
                        "default": "common",
                        "description": "Which dbt project to use",
                    },
                    "models": {
                        "type": "string",
                        "description": "dbt selector (model name, +model+, tag:myTag)",
                    },
                    "target": {
                        "type": "string",
                        "description": "Override profile target (e.g., dev, stage). Defaults to profiles.yml default.",
                    },
                    "full_refresh": {
                        "type": "boolean",
                        "default": False,
                        "description": "Include --full-refresh flag",
                    },
                },
                "required": ["models"],
            },
        ),
        Tool(
            name="dbt_test",
            description="Run dbt tests for specific model(s). Returns pass/fail/warn/error for each test.",
            inputSchema={
                "type": "object",
                "properties": {
                    "models": {
                        "type": "string",
                        "description": "dbt selector for models to test",
                    },
                    "project": {
                        "type": "string",
                        "enum": ["common", "ui"],
                        "default": "common",
                        "description": "Which dbt project to use",
                    },
                },
                "required": ["models"],
            },
        ),
        Tool(
            name="dbt_lineage",
            description="Show upstream and downstream dependencies for a dbt model from manifest.json. Runs dbt parse if manifest is stale.",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {"type": "string", "description": "Model name (without ref wrapper)"},
                    "project": {
                        "type": "string",
                        "enum": ["common", "ui"],
                        "default": "common",
                        "description": "Which dbt project to use",
                    },
                    "depth": {
                        "type": "integer",
                        "default": 3,
                        "description": "How many levels deep to traverse (default 3)",
                    },
                },
                "required": ["model"],
            },
        ),
        Tool(
            name="dbt_show",
            description="Preview query results for a model without materializing. Like a dry-run SELECT.",
            inputSchema={
                "type": "object",
                "properties": {
                    "models": {
                        "type": "string",
                        "description": "dbt selector (single model recommended)",
                    },
                    "project": {
                        "type": "string",
                        "enum": ["common", "ui"],
                        "default": "common",
                        "description": "Which dbt project to use",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "description": "Max rows to preview (default 10)",
                    },
                },
                "required": ["models"],
            },
        ),
        Tool(
            name="dbt_list",
            description="List dbt resources (models, tests, sources) matching a selector.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "dbt selector syntax (model name, tag:x, path:x, +model+)",
                    },
                    "resource_type": {
                        "type": "string",
                        "enum": ["model", "test", "source", "seed", "snapshot", "all"],
                        "default": "model",
                        "description": "Which resource type to list",
                    },
                    "project": {
                        "type": "string",
                        "enum": ["common", "ui"],
                        "default": "common",
                        "description": "Which dbt project to use",
                    },
                },
                "required": ["selector"],
            },
        ),
    ])

    return tools


@app.call_tool()
async def call_tool(name, arguments):
    with audit_tool_call(name, arguments):
        loop = asyncio.get_event_loop()

        # --- dbt Cloud tools ---
        if name == "dbt_cloud_list_jobs":
            path = "jobs/"
            if arguments.get("project_id"):
                path += f"?project_id={arguments['project_id']}"
            result = await loop.run_in_executor(
                None, lambda: _dbt_cloud_request("GET", path)
            )

        elif name == "dbt_cloud_trigger_job":
            body = {"cause": arguments["cause"]}
            if arguments.get("git_sha"):
                body["git_sha"] = arguments["git_sha"]
            result = await loop.run_in_executor(
                None,
                lambda: _dbt_cloud_request(
                    "POST", f"jobs/{arguments['job_id']}/run/", body
                ),
            )

        elif name == "dbt_cloud_run_status":
            result = await loop.run_in_executor(
                None,
                lambda: _dbt_cloud_request(
                    "GET", f"runs/{arguments['run_id']}/"
                ),
            )

        elif name == "dbt_cloud_list_runs":
            params = []
            if arguments.get("job_id"):
                params.append(f"job_definition_id={arguments['job_id']}")
            if arguments.get("status"):
                status_map = {
                    "queued": 1,
                    "starting": 2,
                    "running": 3,
                    "success": 10,
                    "error": 20,
                    "cancelled": 30,
                }
                params.append(f"status={status_map.get(arguments['status'], arguments['status'])}")
            limit = arguments.get("limit", 10)
            params.append(f"limit={limit}")
            path = "runs/?" + "&".join(params)
            result = await loop.run_in_executor(
                None, lambda: _dbt_cloud_request("GET", path)
            )

        elif name == "dbt_cloud_get_artifact":
            run_id = arguments["run_id"]
            artifact = arguments["artifact"]
            result = await loop.run_in_executor(
                None,
                lambda: _dbt_cloud_request(
                    "GET", f"runs/{run_id}/artifacts/{artifact}"
                ),
            )

        elif name == "dbt_cloud_get_latest_artifacts":
            job_id = arguments["job_id"]
            artifact = arguments["artifact"]
            runs_response = await loop.run_in_executor(
                None,
                lambda: _dbt_cloud_request(
                    "GET",
                    f"runs/?job_definition_id={job_id}&status=10&limit=1&order_by=-finished_at",
                ),
            )
            if runs_response.get("error"):
                result = runs_response
            else:
                runs = runs_response.get("data", [])
                if not runs:
                    result = {
                        "error": True,
                        "details": {
                            "message": f"No successful runs found for job {job_id}"
                        },
                    }
                else:
                    run_id = runs[0]["id"]
                    artifact_data = await loop.run_in_executor(
                        None,
                        lambda: _dbt_cloud_request(
                            "GET", f"runs/{run_id}/artifacts/{artifact}"
                        ),
                    )
                    result = {
                        "run_id": run_id,
                        "artifact": artifact,
                        "data": artifact_data,
                    }

        elif name == "dbt_cloud_get_environment":
            project_id = arguments["project_id"]
            result = await loop.run_in_executor(
                None,
                lambda: _dbt_cloud_request(
                    "GET", f"projects/{project_id}/environments/"
                ),
            )

        elif name == "dbt_compile":
            project_root = _resolve_project_root(arguments.get("project", "common"))
            args = ["compile"]
            if arguments.get("full_refresh"):
                args.append("--full-refresh")
            result = await loop.run_in_executor(
                None,
                lambda: _run_dbt_command(args, project_root, DBT_COMPILE_TIMEOUT),
            )
            if result.get("success"):
                compiled_path = Path(project_root) / "target" / "compiled"
                compiled_sql = {}
                if compiled_path.exists():
                    for sql_file in compiled_path.rglob("*.sql"):
                        if sql_file.name.lower() in {
                            f.lower() for f in arguments.get("models", "").split()
                        }:
                            compiled_sql[str(sql_file.relative_to(compiled_path))] = sql_file.read_text(encoding="utf-8")
                result["compiled_sql"] = compiled_sql

        elif name == "dbt_run":
            project_root = _resolve_project_root(arguments.get("project", "common"))
            args = ["run"]
            if arguments.get("models"):
                args.extend(["--select", arguments["models"]])
            if arguments.get("target"):
                args.extend(["--target", arguments["target"]])
            if arguments.get("full_refresh"):
                args.append("--full-refresh")
            result = await loop.run_in_executor(
                None,
                lambda: _run_dbt_command(args, project_root, DBT_RUN_TIMEOUT),
            )

        elif name == "dbt_test":
            project_root = _resolve_project_root(arguments.get("project", "common"))
            args = ["test", "--select", arguments["models"]]
            result = await loop.run_in_executor(
                None,
                lambda: _run_dbt_command(args, project_root, DBT_RUN_TIMEOUT),
            )

        elif name == "dbt_lineage":
            project_root = _resolve_project_root(arguments.get("project", "common"))
            depth = arguments.get("depth", 3)
            result = await loop.run_in_executor(
                None,
                lambda: _get_lineage(arguments["model"], project_root, depth),
            )

        elif name == "dbt_show":
            project_root = _resolve_project_root(arguments.get("project", "common"))
            args = ["show", "--select", arguments["models"], "--limit", str(arguments.get("limit", 10))]
            result = await loop.run_in_executor(
                None,
                lambda: _run_dbt_command(args, project_root, DBT_RUN_TIMEOUT),
            )

        elif name == "dbt_list":
            project_root = _resolve_project_root(arguments.get("project", "common"))
            args = ["list", "--select", arguments["selector"]]
            resource_type = arguments.get("resource_type", "model")
            if resource_type != "all":
                args.extend(["--resource-type", resource_type])
            result = await loop.run_in_executor(
                None,
                lambda: _run_dbt_command(args, project_root, DBT_COMPILE_TIMEOUT),
            )

        else:
            result = {"error": True, "message": f"Unknown tool: {name}"}

        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def main():
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
