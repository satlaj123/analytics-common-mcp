"""
SQL Server MCP Server - database browsing, schema inspection, and read-only queries via ODBC.

"""

import json
import os
import sys
import asyncio
from mcp.server import Server
from mcp.types import Tool, TextContent

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.audit import audit_tool_call

try:
    import pyodbc
    HAS_PYODBC = True
except ImportError:
    HAS_PYODBC = False

app = Server("sqlserver-mcp")

SQLSERVER_HOST = os.environ.get("SQLSERVER_HOST", "invawsdedb01")
SQLSERVER_DRIVER = os.environ.get("SQLSERVER_DRIVER", "ODBC Driver 17 for SQL Server")
SQLSERVER_DATABASE = os.environ.get("SQLSERVER_DATABASE", "master")
SQLSERVER_USER = os.environ.get("SQLSERVER_USER", "")
SQLSERVER_PASSWORD = os.environ.get("SQLSERVER_PASSWORD", "")
MAX_ROWS = 500


def _get_connection(database=None):
    db = database or SQLSERVER_DATABASE
    if SQLSERVER_USER and SQLSERVER_PASSWORD:
        conn_str = (
            f"DRIVER={{{SQLSERVER_DRIVER}}};"
            f"SERVER={SQLSERVER_HOST};"
            f"DATABASE={db};"
            f"UID={SQLSERVER_USER};"
            f"PWD={SQLSERVER_PASSWORD};"
            f"TrustServerCertificate=yes;"
        )
    else:
        conn_str = (
            f"DRIVER={{{SQLSERVER_DRIVER}}};"
            f"SERVER={SQLSERVER_HOST};"
            f"DATABASE={db};"
            f"Trusted_Connection=yes;"
            f"TrustServerCertificate=yes;"
        )
    return pyodbc.connect(conn_str, timeout=30)


def _execute_query(query, database=None, max_rows=None):
    max_rows = max_rows or MAX_ROWS
    try:
        conn = _get_connection(database)
        cursor = conn.cursor()
        cursor.execute(query)

        if cursor.description:
            columns = [col[0] for col in cursor.description]
            rows = cursor.fetchmany(max_rows)
            result = {
                "columns": columns,
                "rows": [
                    dict(zip(columns, [str(v) if v is not None else None for v in row]))
                    for row in rows
                ],
                "row_count": len(rows),
                "truncated": len(rows) == max_rows,
            }
        else:
            result = {"status": "executed", "rowcount": cursor.rowcount}

        cursor.close()
        conn.close()
        return result
    except pyodbc.Error as e:
        return {"error": True, "message": str(e)}
    except Exception as e:
        return {"error": True, "message": str(e)}


@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="sqlserver_list_databases",
            description="List all databases on the SQL Server instance.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="sqlserver_list_tables",
            description="List all tables and views in a specific database, optionally filtered by schema or name pattern.",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": "Database name"},
                    "schema": {"type": "string", "description": "Optional: filter by schema (e.g., 'dbo')"},
                    "search": {"type": "string", "description": "Optional: filter table names containing this text"},
                },
                "required": ["database"],
            },
        ),
        Tool(
            name="sqlserver_describe_table",
            description="Get column names, data types, and nullable info for a table.",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": "Database name"},
                    "table": {"type": "string", "description": "Table name (optionally schema-qualified: schema.table)"},
                },
                "required": ["database", "table"],
            },
        ),
        Tool(
            name="sqlserver_query",
            description="Execute a read-only SELECT query. Only SELECT statements are allowed (no INSERT/UPDATE/DELETE/DROP).",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": "Database name to query"},
                    "query": {"type": "string", "description": "SQL SELECT query to execute"},
                    "max_rows": {"type": "integer", "default": 100, "description": "Maximum rows to return (max 500)"},
                },
                "required": ["database", "query"],
            },
        ),
        Tool(
            name="sqlserver_search_objects",
            description="Search for tables, views, stored procedures, or columns across a database by name pattern.",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": "Database name to search in"},
                    "search": {"type": "string", "description": "Text to search for (case-insensitive)"},
                    "object_type": {
                        "type": "string",
                        "description": "Type to search: 'table', 'view', 'procedure', 'column', 'all'",
                        "enum": ["table", "view", "procedure", "column", "all"],
                        "default": "all",
                    },
                },
                "required": ["database", "search"],
            },
        ),
        Tool(
            name="sqlserver_table_row_counts",
            description="Get row counts for all tables in a database (useful for understanding data volumes).",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": "Database name"},
                    "schema": {"type": "string", "description": "Optional: filter by schema"},
                },
                "required": ["database"],
            },
        ),
        Tool(
            name="sqlserver_list_schemas",
            description="List all schemas in a database.",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": "Database name"},
                },
                "required": ["database"],
            },
        ),
        Tool(
            name="sqlserver_list_jobs",
            description="List all SQL Server Agent jobs with their schedule, last run status, and next run time.",
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Optional: filter job names containing this text"},
                    "status": {
                        "type": "string",
                        "description": "Optional: filter by last run status",
                        "enum": ["succeeded", "failed", "running", "all"],
                        "default": "all",
                    },
                },
            },
        ),
        Tool(
            name="sqlserver_job_history",
            description="Show recent run history for a specific SQL Agent job (pass/fail, duration, messages).",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_name": {"type": "string", "description": "Job name (or partial match)"},
                    "limit": {"type": "integer", "default": 20, "description": "Number of history records to return"},
                },
                "required": ["job_name"],
            },
        ),
        Tool(
            name="sqlserver_replication_status",
            description="Check replication task status, latency, and recent activity.",
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Optional: filter by publication or subscription name"},
                },
            },
        ),
        Tool(
            name="sqlserver_ssis_executions",
            description="List recent SSIS package executions from the SSISDB catalog (status, duration, errors).",
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Optional: filter by package or project name"},
                    "status": {
                        "type": "string",
                        "description": "Optional: filter by status",
                        "enum": ["success", "failed", "running", "all"],
                        "default": "all",
                    },
                    "limit": {"type": "integer", "default": 20, "description": "Number of executions to return"},
                },
            },
        ),
    ]


@app.call_tool()
async def call_tool(name, arguments):
    with audit_tool_call("sqlserver", name, arguments) as audit:
        if not HAS_PYODBC:
            return [TextContent(type="text", text="ERROR: pyodbc not installed. Run: py -3.12 -m pip install pyodbc")]

        loop = asyncio.get_event_loop()

        if name == "sqlserver_list_databases":
            query = "SELECT name, state_desc, create_date FROM sys.databases ORDER BY name"
            result = await loop.run_in_executor(None, lambda: _execute_query(query, "master"))

        elif name == "sqlserver_list_tables":
            database = arguments["database"]
            schema_filter = arguments.get("schema", "")
            search = arguments.get("search", "")

            query = """
                SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
                FROM INFORMATION_SCHEMA.TABLES
                WHERE 1=1
            """
            if schema_filter:
                query += f" AND TABLE_SCHEMA = '{schema_filter}'"
            if search:
                query += f" AND TABLE_NAME LIKE '%{search}%'"
            query += " ORDER BY TABLE_SCHEMA, TABLE_NAME"

            result = await loop.run_in_executor(
                None, lambda: _execute_query(query, database)
            )

        elif name == "sqlserver_describe_table":
            database = arguments["database"]
            table = arguments["table"]

            if "." in table:
                schema, tbl = table.split(".", 1)
            else:
                schema, tbl = "dbo", table

            query = f"""
                SELECT
                    c.COLUMN_NAME,
                    c.DATA_TYPE,
                    c.CHARACTER_MAXIMUM_LENGTH,
                    c.NUMERIC_PRECISION,
                    c.IS_NULLABLE,
                    c.COLUMN_DEFAULT,
                    CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 'YES' ELSE 'NO' END AS IS_PRIMARY_KEY
                FROM INFORMATION_SCHEMA.COLUMNS c
                LEFT JOIN (
                    SELECT ku.TABLE_SCHEMA, ku.TABLE_NAME, ku.COLUMN_NAME
                    FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                    JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                        ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
                    WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                ) pk ON c.TABLE_SCHEMA = pk.TABLE_SCHEMA
                    AND c.TABLE_NAME = pk.TABLE_NAME
                    AND c.COLUMN_NAME = pk.COLUMN_NAME
                WHERE c.TABLE_SCHEMA = '{schema}' AND c.TABLE_NAME = '{tbl}'
                ORDER BY c.ORDINAL_POSITION
            """
            result = await loop.run_in_executor(
                None, lambda: _execute_query(query, database)
            )

        elif name == "sqlserver_query":
            database = arguments["database"]
            query = arguments["query"].strip()
            max_rows = min(arguments.get("max_rows", 100), MAX_ROWS)

            forbidden = ["INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "CREATE ", "TRUNCATE ", "EXEC ", "EXECUTE "]
            query_upper = query.upper()
            for kw in forbidden:
                if kw in query_upper:
                    return [TextContent(type="text", text=f"ERROR: Only SELECT queries are allowed. Detected: {kw.strip()}")]

            if not query_upper.startswith("SELECT") and not query_upper.startswith("WITH"):
                return [TextContent(type="text", text="ERROR: Query must start with SELECT or WITH (CTE).")]

            result = await loop.run_in_executor(
                None, lambda: _execute_query(query, database, max_rows)
            )

        elif name == "sqlserver_search_objects":
            database = arguments["database"]
            search = arguments["search"]
            obj_type = arguments.get("object_type", "all")

            queries = []
            if obj_type in ("table", "all"):
                queries.append(f"""
                    SELECT 'TABLE' AS object_type, TABLE_SCHEMA AS schema_name, TABLE_NAME AS object_name
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_NAME LIKE '%{search}%'
                """)
            if obj_type in ("view", "all"):
                queries.append(f"""
                    SELECT 'VIEW' AS object_type, TABLE_SCHEMA AS schema_name, TABLE_NAME AS object_name
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_TYPE = 'VIEW' AND TABLE_NAME LIKE '%{search}%'
                """)
            if obj_type in ("procedure", "all"):
                queries.append(f"""
                    SELECT 'PROCEDURE' AS object_type, ROUTINE_SCHEMA AS schema_name, ROUTINE_NAME AS object_name
                    FROM INFORMATION_SCHEMA.ROUTINES
                    WHERE ROUTINE_TYPE = 'PROCEDURE' AND ROUTINE_NAME LIKE '%{search}%'
                """)
            if obj_type in ("column", "all"):
                queries.append(f"""
                    SELECT 'COLUMN' AS object_type, TABLE_SCHEMA + '.' + TABLE_NAME AS schema_name, COLUMN_NAME AS object_name
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE COLUMN_NAME LIKE '%{search}%'
                """)

            full_query = " UNION ALL ".join(queries) + " ORDER BY object_type, schema_name, object_name"
            result = await loop.run_in_executor(
                None, lambda: _execute_query(full_query, database)
            )

        elif name == "sqlserver_table_row_counts":
            database = arguments["database"]
            schema_filter = arguments.get("schema", "")

            query = """
                SELECT
                    s.name AS schema_name,
                    t.name AS table_name,
                    p.rows AS row_count
                FROM sys.tables t
                JOIN sys.schemas s ON t.schema_id = s.schema_id
                JOIN sys.partitions p ON t.object_id = p.object_id AND p.index_id IN (0, 1)
            """
            if schema_filter:
                query += f" WHERE s.name = '{schema_filter}'"
            query += " ORDER BY p.rows DESC"

            result = await loop.run_in_executor(
                None, lambda: _execute_query(query, database)
            )

        elif name == "sqlserver_list_schemas":
            database = arguments["database"]
            query = "SELECT SCHEMA_NAME, SCHEMA_OWNER FROM INFORMATION_SCHEMA.SCHEMATA ORDER BY SCHEMA_NAME"
            result = await loop.run_in_executor(
                None, lambda: _execute_query(query, database)
            )

        elif name == "sqlserver_list_jobs":
            search = arguments.get("search", "")
            status = arguments.get("status", "all")

            query = """
                SELECT
                    j.name AS job_name,
                    CASE j.enabled WHEN 1 THEN 'Enabled' ELSE 'Disabled' END AS status,
                    CASE h.run_status
                        WHEN 0 THEN 'Failed'
                        WHEN 1 THEN 'Succeeded'
                        WHEN 2 THEN 'Retry'
                        WHEN 3 THEN 'Cancelled'
                        WHEN 4 THEN 'Running'
                        ELSE 'Unknown'
                    END AS last_run_status,
                    STUFF(STUFF(CAST(h.run_date AS VARCHAR(8)), 5, 0, '-'), 8, 0, '-') AS last_run_date,
                    STUFF(STUFF(RIGHT('000000' + CAST(h.run_time AS VARCHAR(6)), 6), 3, 0, ':'), 6, 0, ':') AS last_run_time,
                    CAST(h.run_duration / 10000 AS VARCHAR) + 'h ' +
                    CAST((h.run_duration % 10000) / 100 AS VARCHAR) + 'm ' +
                    CAST(h.run_duration % 100 AS VARCHAR) + 's' AS duration,
                    j.description
                FROM msdb.dbo.sysjobs j
                LEFT JOIN (
                    SELECT job_id, run_status, run_date, run_time, run_duration,
                           ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY run_date DESC, run_time DESC) AS rn
                    FROM msdb.dbo.sysjobhistory
                    WHERE step_id = 0
                ) h ON j.job_id = h.job_id AND h.rn = 1
                WHERE 1=1
            """
            if search:
                query += f" AND j.name LIKE '%{search}%'"
            if status == "succeeded":
                query += " AND h.run_status = 1"
            elif status == "failed":
                query += " AND h.run_status = 0"
            elif status == "running":
                query += " AND h.run_status = 4"
            query += " ORDER BY h.run_date DESC, h.run_time DESC"

            result = await loop.run_in_executor(
                None, lambda: _execute_query(query, "msdb")
            )

        elif name == "sqlserver_job_history":
            job_name = arguments["job_name"]
            limit = min(arguments.get("limit", 20), 100)

            query = f"""
                SELECT TOP {limit}
                    j.name AS job_name,
                    CASE h.run_status
                        WHEN 0 THEN 'Failed'
                        WHEN 1 THEN 'Succeeded'
                        WHEN 2 THEN 'Retry'
                        WHEN 3 THEN 'Cancelled'
                        WHEN 4 THEN 'Running'
                        ELSE 'Unknown'
                    END AS run_status,
                    h.step_name,
                    STUFF(STUFF(CAST(h.run_date AS VARCHAR(8)), 5, 0, '-'), 8, 0, '-') AS run_date,
                    STUFF(STUFF(RIGHT('000000' + CAST(h.run_time AS VARCHAR(6)), 6), 3, 0, ':'), 6, 0, ':') AS run_time,
                    CAST(h.run_duration / 10000 AS VARCHAR) + 'h ' +
                    CAST((h.run_duration % 10000) / 100 AS VARCHAR) + 'm ' +
                    CAST(h.run_duration % 100 AS VARCHAR) + 's' AS duration,
                    h.message
                FROM msdb.dbo.sysjobhistory h
                JOIN msdb.dbo.sysjobs j ON h.job_id = j.job_id
                WHERE j.name LIKE '%{job_name}%'
                    AND h.step_id = 0
                ORDER BY h.run_date DESC, h.run_time DESC
            """
            result = await loop.run_in_executor(
                None, lambda: _execute_query(query, "msdb", limit)
            )

        elif name == "sqlserver_replication_status":
            search = arguments.get("search", "")

            query = """
                SELECT
                    p.name AS publication_name,
                    p.status AS pub_status,
                    a.publisher_db,
                    a.publication,
                    a.subscriber_db,
                    s.status AS subscription_status,
                    CASE s.status
                        WHEN 0 THEN 'Inactive'
                        WHEN 1 THEN 'Subscribed'
                        WHEN 2 THEN 'Active'
                        ELSE 'Unknown'
                    END AS status_desc
                FROM distribution.dbo.MSpublications p
                LEFT JOIN distribution.dbo.MSsubscriptions s ON p.publication_id = s.publication_id
                LEFT JOIN distribution.dbo.MSarticles a ON p.publication_id = a.publication_id
                WHERE 1=1
            """
            if search:
                query += f" AND (p.name LIKE '%{search}%' OR a.publisher_db LIKE '%{search}%')"
            query += " ORDER BY p.name"

            try:
                result = await loop.run_in_executor(
                    None, lambda: _execute_query(query, "distribution")
                )
            except Exception:
                result = {"message": "Distribution database not accessible or replication not configured on this server."}

        elif name == "sqlserver_ssis_executions":
            search = arguments.get("search", "")
            status = arguments.get("status", "all")
            limit = min(arguments.get("limit", 20), 100)

            query = f"""
                SELECT TOP {limit}
                    e.execution_id,
                    e.project_name,
                    e.package_name,
                    CASE e.status
                        WHEN 1 THEN 'Created'
                        WHEN 2 THEN 'Running'
                        WHEN 3 THEN 'Cancelled'
                        WHEN 4 THEN 'Failed'
                        WHEN 5 THEN 'Pending'
                        WHEN 6 THEN 'Ended unexpectedly'
                        WHEN 7 THEN 'Succeeded'
                        WHEN 8 THEN 'Stopping'
                        WHEN 9 THEN 'Completed'
                        ELSE 'Unknown'
                    END AS status,
                    e.start_time,
                    e.end_time,
                    DATEDIFF(SECOND, e.start_time, ISNULL(e.end_time, GETDATE())) AS duration_seconds,
                    e.caller_name
                FROM SSISDB.catalog.executions e
                WHERE 1=1
            """
            if search:
                query += f" AND (e.project_name LIKE '%{search}%' OR e.package_name LIKE '%{search}%')"
            if status == "success":
                query += " AND e.status = 7"
            elif status == "failed":
                query += " AND e.status = 4"
            elif status == "running":
                query += " AND e.status = 2"
            query += " ORDER BY e.start_time DESC"

            try:
                result = await loop.run_in_executor(
                    None, lambda: _execute_query(query, "SSISDB", limit)
                )
            except Exception:
                result = {"message": "SSISDB not accessible or SSIS not configured on this server."}

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def main():
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
