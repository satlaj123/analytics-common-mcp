"""AWS MCP Server - tool definitions and routing."""
import asyncio
import json
from mcp.server import Server
from mcp.types import Tool, TextContent

from .config import load_config
from .session import SessionManager
from .tools import step_functions, lambda_tools, s3, cloudwatch, eventbridge, dms

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
from shared.audit import audit_tool_call

app = Server("aws-mcp")
config = load_config()
session_mgr = SessionManager(config)

@app.list_tools()
async def list_tools():
    return [
        # Step Functions
        Tool(
            name="list_pipelines",
            description="List all Step Function state machines grouped by naming prefix.",
            inputSchema={"type": "object", "properties": {
                "account": {"type": "string", "enum": ["pipeline", "dev"], "default": "pipeline",
                    "description": "Which account to query (default: pipeline)"},
            }},
        ),
        Tool(
            name="get_pipeline_status",
            description="Show last 5 execution results for a Step Function pipeline with pass/fail and duration.",
            inputSchema={"type": "object", "properties": {
                "pipeline_name": {"type": "string", "description": "Name or partial name of the state machine"},
                "account": {"type": "string", "enum": ["pipeline", "dev"], "default": "pipeline"},
            }, "required": ["pipeline_name"]},
        ),
        Tool(
            name="get_pipeline_history",
            description="Execution history over N days with success rate percentage.",
            inputSchema={"type": "object", "properties": {
                "pipeline_name": {"type": "string", "description": "Name or partial name of the state machine"},
                "days": {"type": "integer", "default": 7, "description": "Number of days to look back"},
                "account": {"type": "string", "enum": ["pipeline", "dev"], "default": "pipeline"},
            }, "required": ["pipeline_name"]},
        ),
        Tool(
            name="get_execution_details",
            description="Step-by-step trace of a specific execution including error messages.",
            inputSchema={"type": "object", "properties": {
                "execution_arn": {"type": "string", "description": "Full execution ARN"},
                "account": {"type": "string", "enum": ["pipeline", "dev"], "default": "pipeline"},
            }, "required": ["execution_arn"]},
        ),
        # Lambda
        Tool(
            name="list_functions",
            description="List all Lambda functions with runtime, memory, timeout, and last modified.",
            inputSchema={"type": "object", "properties": {
                "account": {"type": "string", "enum": ["pipeline", "dev"], "default": "pipeline"},
            }},
        ),
        Tool(
            name="get_function_details",
            description="Detailed Lambda config including env var names, layers, and handler.",
            inputSchema={"type": "object", "properties": {
                "function_name": {"type": "string", "description": "Lambda function name"},
                "account": {"type": "string", "enum": ["pipeline", "dev"], "default": "pipeline"},
            }, "required": ["function_name"]},
        ),
        Tool(
            name="get_lambda_errors",
            description="Pull ERROR/Exception/Traceback logs from CloudWatch for a Lambda function.",
            inputSchema={"type": "object", "properties": {
                "function_name": {"type": "string", "description": "Lambda function name"},
                "hours": {"type": "integer", "default": 24, "description": "Hours to look back"},
                "account": {"type": "string", "enum": ["pipeline", "dev"], "default": "pipeline"},
            }, "required": ["function_name"]},
        ),
        # S3
        Tool(
            name="list_buckets",
            description="List all S3 buckets in the account.",
            inputSchema={"type": "object", "properties": {
                "account": {"type": "string", "enum": ["pipeline", "dev"], "default": "pipeline"},
            }},
        ),
        Tool(
            name="check_file_exists",
            description="Verify a specific S3 file exists with size and last modified time.",
            inputSchema={"type": "object", "properties": {
                "bucket": {"type": "string", "description": "S3 bucket name"},
                "key": {"type": "string", "description": "Object key (path within the bucket)"},
                "account": {"type": "string", "enum": ["pipeline", "dev"], "default": "pipeline"},
            }, "required": ["bucket", "key"]},
        ),
        Tool(
            name="list_recent_files",
            description="List files modified in the last N hours (data landing check).",
            inputSchema={"type": "object", "properties": {
                "bucket": {"type": "string", "description": "S3 bucket name"},
                "prefix": {"type": "string", "default": "", "description": "Optional prefix to filter"},
                "hours": {"type": "integer", "default": 24, "description": "Hours to look back"},
                "account": {"type": "string", "enum": ["pipeline", "dev"], "default": "pipeline"},
            }, "required": ["bucket"]},
        ),
        Tool(
            name="list_prefixes",
            description="Browse S3 folder structure at any path.",
            inputSchema={"type": "object", "properties": {
                "bucket": {"type": "string", "description": "S3 bucket name"},
                "prefix": {"type": "string", "default": "", "description": "Prefix/folder path to list"},
                "account": {"type": "string", "enum": ["pipeline", "dev"], "default": "pipeline"},
            }, "required": ["bucket"]},
        ),
        # CloudWatch
        Tool(
            name="search_logs",
            description="Search any CloudWatch log group with filter patterns.",
            inputSchema={"type": "object", "properties": {
                "log_group": {"type": "string", "description": "Full log group name"},
                "filter_pattern": {"type": "string", "default": "", "description": "CloudWatch filter pattern"},
                "hours": {"type": "integer", "default": 24, "description": "Hours to look back"},
                "account": {"type": "string", "enum": ["pipeline", "dev"], "default": "pipeline"},
            }, "required": ["log_group"]},
        ),
        Tool(
            name="list_log_groups",
            description="Discover available CloudWatch log groups by prefix.",
            inputSchema={"type": "object", "properties": {
                "prefix": {"type": "string", "default": "", "description": "Optional prefix filter"},
                "account": {"type": "string", "enum": ["pipeline", "dev"], "default": "pipeline"},
            }},
        ),
        Tool(
            name="get_step_function_logs",
            description="Shortcut to search a pipeline's error logs in CloudWatch.",
            inputSchema={"type": "object", "properties": {
                "pipeline_name": {"type": "string", "description": "Pipeline name"},
                "hours": {"type": "integer", "default": 24, "description": "Hours to look back"},
                "account": {"type": "string", "enum": ["pipeline", "dev"], "default": "pipeline"},
            }, "required": ["pipeline_name"]},
        ),
        # EventBridge
        Tool(
            name="list_rules",
            description="List all EventBridge rules with cron/rate schedules and enabled/disabled state.",
            inputSchema={"type": "object", "properties": {
                "account": {"type": "string", "enum": ["pipeline", "dev"], "default": "pipeline"},
            }},
        ),
        Tool(
            name="get_rule_targets",
            description="Show what an EventBridge rule triggers (Step Function, Lambda, SNS, etc.).",
            inputSchema={"type": "object", "properties": {
                "rule_name": {"type": "string", "description": "EventBridge rule name"},
                "account": {"type": "string", "enum": ["pipeline", "dev"], "default": "pipeline"},
            }, "required": ["rule_name"]},
        ),
        # DMS
        Tool(
            name="list_replication_tasks",
            description="List all DMS replication tasks with status, migration type, and table counts.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_replication_stats",
            description="Get CDC latency, table load progress, and error messages for a DMS task.",
            inputSchema={"type": "object", "properties": {
                "task_identifier": {"type": "string", "default": "", "description": "Task identifier (partial match)"},
            }},
        ),
        Tool(
            name="list_endpoints",
            description="List all DMS source and target database connection endpoints.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]

@app.call_tool()
async def call_tool(name, arguments):
    with audit_tool_call("aws", name, arguments) as audit:
        loop = asyncio.get_event_loop()
        account = arguments.get("account", "pipeline")
        try:
            if name == "list_pipelines":
                result = await loop.run_in_executor(None, lambda: step_functions.list_pipelines(session_mgr, account))
            elif name == "get_pipeline_status":
                result = await loop.run_in_executor(None, lambda: step_functions.get_pipeline_status(session_mgr, arguments["pipeline_name"], account))
            elif name == "get_pipeline_history":
                days = arguments.get("days", 7)
                result = await loop.run_in_executor(None, lambda: step_functions.get_pipeline_history(session_mgr, arguments["pipeline_name"], days, account))
            elif name == "get_execution_details":
                result = await loop.run_in_executor(None, lambda: step_functions.get_execution_details(session_mgr, arguments["execution_arn"], account))
            elif name == "list_functions":
                result = await loop.run_in_executor(None, lambda: lambda_tools.list_functions(session_mgr, account))
            elif name == "get_function_details":
                result = await loop.run_in_executor(None, lambda: lambda_tools.get_function_details(session_mgr, arguments["function_name"], account))
            elif name == "get_lambda_errors":
                hours = arguments.get("hours", 24)
                result = await loop.run_in_executor(None, lambda: lambda_tools.get_lambda_errors(session_mgr, arguments["function_name"], hours, account))
            elif name == "list_buckets":
                result = await loop.run_in_executor(None, lambda: s3.list_buckets(session_mgr, account))
            elif name == "check_file_exists":
                result = await loop.run_in_executor(None, lambda: s3.check_file_exists(session_mgr, arguments["bucket"], arguments["key"], account))
            elif name == "list_recent_files":
                hours = arguments.get("hours", 24)
                prefix = arguments.get("prefix", "")
                result = await loop.run_in_executor(None, lambda: s3.list_recent_files(session_mgr, arguments["bucket"], prefix, hours, account))
            elif name == "list_prefixes":
                prefix = arguments.get("prefix", "")
                result = await loop.run_in_executor(None, lambda: s3.list_prefixes(session_mgr, arguments["bucket"], prefix, account))
            elif name == "search_logs":
                hours = arguments.get("hours", 24)
                pattern = arguments.get("filter_pattern", "")
                result = await loop.run_in_executor(None, lambda: cloudwatch.search_logs(session_mgr, arguments["log_group"], pattern, hours, account))
            elif name == "list_log_groups":
                prefix = arguments.get("prefix", "")
                result = await loop.run_in_executor(None, lambda: cloudwatch.list_log_groups(session_mgr, prefix, account))
            elif name == "get_step_function_logs":
                hours = arguments.get("hours", 24)
                result = await loop.run_in_executor(None, lambda: cloudwatch.get_step_function_logs(session_mgr, arguments["pipeline_name"], hours, account))
            elif name == "list_rules":
                result = await loop.run_in_executor(None, lambda: eventbridge.list_rules(session_mgr, account))
            elif name == "get_rule_targets":
                result = await loop.run_in_executor(None, lambda: eventbridge.get_rule_targets(session_mgr, arguments["rule_name"], account))
            elif name == "list_replication_tasks":
                if not session_mgr.is_account_configured("dms"):
                    result = "The 'dms' account is not configured. To configure it, add AWS_DMS_* environment variables."
                else:
                    result = await loop.run_in_executor(None, lambda: dms.list_replication_tasks(session_mgr))
            elif name == "get_replication_stats":
                if not session_mgr.is_account_configured("dms"):
                    result = "The 'dms' account is not configured. To configure it, add AWS_DMS_* environment variables."
                else:
                    task_id = arguments.get("task_identifier", "")
                    result = await loop.run_in_executor(None, lambda: dms.get_replication_stats(session_mgr, task_id))
            elif name == "list_endpoints":
                if not session_mgr.is_account_configured("dms"):
                    result = "The 'dms' account is not configured. To configure it, add AWS_DMS_* environment variables."
                else:
                    result = await loop.run_in_executor(None, lambda: dms.list_endpoints(session_mgr))
            else:
                result = f"Unknown tool: {name}"
            return [TextContent(type="text", text=str(result))]
        except ValueError as e:
            return [TextContent(type="text", text=f"Configuration error: {str(e)}")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {type(e).__name__}: {str(e)}")]

async def main():
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())