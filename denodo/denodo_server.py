"""
Denodo MCP Server — metadata browsing, view definitions, data querying via REST API,
and lineage/datasource introspection via VQL (psycopg2 over ODBC port).
"""

import json
import base64
import ssl
import urllib.request
import urllib.error
import urllib.parse
import os
import sys
import asyncio
from mcp.server import Server
from mcp.types import Tool, TextContent

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.credentials import get_secret
from shared.audit import audit_tool_call

try:
    import psycopg2
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

app = Server("denodo-mcp")

DENODO_HOST = os.environ.get("DENODO_HOST", "invawsdeden01.dti.net.net")
DENODO_PORT = os.environ.get("DENODO_PORT", "9443")
DENODO_VDP_PORT = os.environ.get("DENODO_VDP_PORT", "9996")
DENODO_USER = os.environ.get("DENODO_USER", "")
DENODO_PASSWORD = get_secret("mcp-denodo", "password", "DENODO_PASSWORD")
DENODO_BASE_URL = f"https://{DENODO_HOST}:{DENODO_PORT}/denodo-restfulws"

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

ALL_DATABASES = [
    "acquisition_reports", "admin", "connectivity", "cube_metadata",
    "ehs_business_entities", "ehs_reports", "fi_business_entities",
    "fi_data_services", "fi_reports", "general_reports", "integration",
    "it_business_entities", "it_data_services", "it_reports", "itpilot",
    "lg_business_entities", "lg_data_services", "lg_reports",
    "master_data_business_entities", "master_data_reports", "master_data_services",
    "ops_business_entities", "ops_data_services", "ops_reports", "otm_reports",
    "pm_business_entities", "pm_data_services", "pm_reports",
    "pr_business_entities", "pr_data_services", "pr_reports",
    "scm_business_entities", "scm_data_services", "scm_reports",
    "tm_business_entities", "tm_reports",
]


def _get_auth_header():
    credentials = base64.b64encode(
        f"{DENODO_USER}:{DENODO_PASSWORD}".encode()
    ).decode()
    return f"Basic {credentials}"


def _denodo_request(method, url, body=None, timeout=30):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", _get_auth_header())
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, context=_ssl_ctx, timeout=timeout) as resp:
            raw = resp.read().decode()
            if not raw:
                return {"status": "success", "code": resp.status}
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        try:
            error_json = json.loads(error_body)
        except (json.JSONDecodeError, ValueError):
            error_json = {"message": error_body}
        return {"error": True, "status": e.code, "details": error_json}
    except urllib.error.URLError as e:
        return {"error": True, "details": {"message": str(e.reason)}}
    except Exception as e:
        return {"error": True, "details": {"message": str(e)}}


def _vql_query(sql, database="connectivity", timeout=30):
    if not HAS_PSYCOPG2:
        return {
            "error": True,
            "details": {
                "message": "psycopg2 not installed. Run: pip install psycopg2-binary"
            },
        }
    try:
        conn = psycopg2.connect(
            host=DENODO_HOST,
            port=int(DENODO_VDP_PORT),
            database=database,
            user=DENODO_USER,
            password=DENODO_PASSWORD,
            connect_timeout=timeout,
            sslmode="require",
        )
        cur = conn.cursor()
        cur.execute(sql)
        columns = [desc[0] for desc in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return {"columns": columns, "rows": rows, "count": len(rows)}
    except Exception as e:
        msg = str(e).split("DETAIL")[0].strip()
        return {"error": True, "details": {"message": msg}}


@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="denodo_search",
            description="Search for views across ALL Denodo databases by name pattern. Use this as the primary discovery tool.",
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {
                        "type": "string",
                        "description": "Text to search for in view names (case-insensitive substring match)",
                    }
                },
                "required": ["search"],
            },
        ),
        Tool(
            name="denodo_list_databases",
            description="List all available Denodo databases.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="denodo_list_views",
            description="List all views (virtual tables) in a specific Denodo database with optional search filter.",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {
                        "type": "string",
                        "description": "Database name (default: admin)",
                        "default": "admin",
                    },
                    "search": {
                        "type": "string",
                        "description": "Optional text to filter view names (case-insensitive substring match)",
                    },
                },
            },
        ),
        Tool(
            name="denodo_describe_view",
            description="Get the schema (columns, data types) of a Denodo view.",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": "Database name", "default": "admin"},
                    "view": {"type": "string", "description": "View name"},
                },
                "required": ["view"],
            },
        ),
        Tool(
            name="denodo_view_metadata",
            description="Get full metadata for a view including available links (schema, associations, elements).",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": "Database name", "default": "admin"},
                    "view": {"type": "string", "description": "View name"},
                },
                "required": ["view"],
            },
        ),
        Tool(
            name="denodo_view_associations",
            description="Get associations (relationships/lineage links) for a Denodo view.",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": "Database name", "default": "admin"},
                    "view": {"type": "string", "description": "View name"},
                },
                "required": ["view"],
            },
        ),
        Tool(
            name="denodo_get_view_data",
            description="Query data from a Denodo view with optional filtering. Returns rows as JSON.",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": "Database name", "default": "admin"},
                    "view": {"type": "string", "description": "View name"},
                    "filter": {"type": "string", "description": "Filter condition, e.g. \"\\\"column_name\\\"=value\" (field names are case-sensitive)"},
                    "select": {"type": "string", "description": "Comma-separated column names to return"},
                    "order_by": {"type": "string", "description": "Column to sort by, e.g. DATE ASC"},
                    "max_rows": {"type": "integer", "default": 20, "description": "Maximum rows to return (default 20, max 100)"},
                },
                "required": ["view"],
            },
        ),
        Tool(
            name="denodo_list_datasources",
            description="List all Denodo datasources (JDBC, JSON, LDAP, etc.) across Denodo databases. Shows connection type, creator, and last modifier. Optionally filter by database or name pattern.",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": "Filter to a specific database (optional)"},
                    "search": {"type": "string", "description": "Filter datasource names by substring (case-insensitive, optional)"},
                },
            },
        ),
        Tool(
            name="denodo_view_lineage",
            description="Trace forward lineage from a Denodo view down to its underlying datasource, connection details, and source table. Shows the full dependency chain: published view -> intermediate views -> base view -> datasource -> source table. Also retrieves the datasource VQL definition with server/database/warehouse details.",
            inputSchema={
                "type": "object",
                "properties": {
                    "database": {"type": "string", "description": "Database name where the view lives"},
                    "view": {"type": "string", "description": "View name to trace lineage for"},
                },
                "required": ["database", "view"],
            },
        ),
        Tool(
            name="denodo_reverse_lineage",
            description="Find all base views built on a given datasource. Base views connect directly to datasources, so this shows every table/view that pulls from that connection. Returns base view names, source catalog/schema/table, and folder. NOTE: This scans all base views in the datasource's database and may take 2-4 minutes. Use denodo_view_lineage on a returned base view to trace its downstream consumers.",
            inputSchema={
                "type": "object",
                "properties": {
                    "datasource": {
                        "type": "string",
                        "description": "Datasource name (e.g. 'ds_snowflake_osi_pi_small'). Use denodo_list_datasources to find names.",
                    }
                },
                "required": ["datasource"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name, arguments):
    with audit_tool_call("denodo", name, arguments) as audit:
        loop = asyncio.get_event_loop()

        if name == "denodo_search":
            search = arguments["search"].lower()
            results_by_db = {}

            async def search_db(db):
                url = f"{DENODO_BASE_URL}/{urllib.parse.quote(db)}"
                raw = await loop.run_in_executor(
                    None, lambda: _denodo_request("GET", url, timeout=15)
                )
                if raw and not raw.get("error") and "views-metadata" in raw:
                    matches = [v for v in raw["views-metadata"] if search in v["name"].lower()]
                    if matches:
                        return db, matches
                return None

            tasks = [search_db(db) for db in ALL_DATABASES]
            search_results = await asyncio.gather(*tasks)
            for r in search_results:
                if r:
                    results_by_db[r[0]] = r[1]

            total = sum(len(v) for v in results_by_db.values())
            result = {"search_term": arguments["search"], "total_matches": total, "results": results_by_db}

        elif name == "denodo_list_databases":
            result = {"databases": ALL_DATABASES, "count": len(ALL_DATABASES)}

        elif name == "denodo_list_views":
            database = arguments.get("database", "admin")
            search = arguments.get("search", "").lower()
            url = f"{DENODO_BASE_URL}/{urllib.parse.quote(database)}"
            raw = await loop.run_in_executor(
                None, lambda: _denodo_request("GET", url, timeout=60)
            )
            if raw.get("error"):
                result = raw
            else:
                views = raw.get("views-metadata", [])
                if search:
                    views = [v for v in views if search in v["name"].lower()]
                result = {"database": database, "views": views, "count": len(views)}

        elif name == "denodo_describe_view":
            database = arguments.get("database", "admin")
            view = arguments["view"]
            url = f"{DENODO_BASE_URL}/{urllib.parse.quote(database)}/{urllib.parse.quote(view)}"
            result = await loop.run_in_executor(
                None, lambda: _denodo_request("GET", url, timeout=30)
            )

        elif name == "denodo_view_metadata":
            database = arguments.get("database", "admin")
            view = arguments["view"]
            url = f"{DENODO_BASE_URL}/{urllib.parse.quote(database)}/{urllib.parse.quote(view)}"
            result = await loop.run_in_executor(
                None, lambda: _denodo_request("GET", url, timeout=30)
            )

        elif name == "denodo_view_associations":
            database = arguments.get("database", "admin")
            view = arguments["view"]
            url = f"{DENODO_BASE_URL}/{urllib.parse.quote(database)}/{urllib.parse.quote(view)}/associations"
            result = await loop.run_in_executor(
                None, lambda: _denodo_request("GET", url, timeout=30)
            )

        elif name == "denodo_get_view_data":
            database = arguments.get("database", "admin")
            view = arguments["view"]
            max_rows = min(int(arguments.get("max_rows", 20)), 100)
            filter_clause = arguments.get("filter", "")
            select_clause = arguments.get("select", "")
            order_by = arguments.get("order_by", "")

            params = {"maxrows": max_rows}
            if filter_clause:
                params["filter"] = filter_clause
            if select_clause:
                params["select"] = select_clause
            if order_by:
                params["orderBy"] = order_by

            query_string = urllib.parse.urlencode(params)
            url = (
                f"{DENODO_BASE_URL}/{urllib.parse.quote(database)}/"
                f"{urllib.parse.quote(view)}/data?{query_string}"
            )
            result = await loop.run_in_executor(
                None, lambda: _denodo_request("GET", url, timeout=60)
            )

        elif name == "denodo_list_datasources":
            db_filter = arguments.get("database", "")
            search = arguments.get("search", "").lower()
            where = "type = 'datasource'"
            if db_filter:
                where += f" AND database_name = '{db_filter}'"

            raw = await loop.run_in_executor(
                None,
                lambda: _vql_query(
                    f"SELECT database_name, name, subtype, user_creator, "
                    f"last_modification_date, create_date, last_modification_date, description "
                    f"FROM GET_ELEMENTS() WHERE {where} "
                    f"ORDER BY database_name, name"
                ),
            )
            if raw.get("error"):
                result = raw
            else:
                rows = raw["rows"]
                if search:
                    rows = [r for r in rows if search in r["name"].lower()]
                result = {"datasources": rows, "count": len(rows)}

        elif name == "denodo_view_lineage":
            database = arguments["database"]
            view = arguments["view"]

            deps_raw = await loop.run_in_executor(
                None,
                lambda: _vql_query(
                    f"SELECT view_database_name, view_name, view_type, "
                    f"dependency_database_name, dependency_name, dependency_type, depth "
                    f"FROM VIEW_DEPENDENCIES('{database}', '{view}', 'false') "
                    f"ORDER BY depth",
                    database=database,
                ),
            )
            if deps_raw.get("error"):
                result = deps_raw
            else:
                deps = deps_raw["rows"]
                chain = []
                datasources = set()
                base_views = set()
                for d in deps:
                    chain.append(d)
                    if d["dependency_type"] == "Jdbc Datasource":
                        datasources.add((d["dependency_database_name"] or database, d["dependency_name"]))
                    if d["dependency_type"] == "Base View":
                        base_views.add((d["dependency_database_name"] or database, d["dependency_name"]))
                    if d["view_type"] == "Base View":
                        base_views.add((d["view_database_name"] or database, d["view_name"]))

                source_tables = []
                for bv_db, bv_name in base_views:
                    src_raw = await loop.run_in_executor(
                        None,
                        lambda bdb=bv_db, bname=bv_name: _vql_query(
                            f"SELECT database_name, view_name, source_catalog_name, "
                            f"source_schema_name, source_table_name "
                            f"FROM GET_SOURCE_TABLE() "
                            f"WHERE input_database_name = '{bdb}' AND input_view_name = '{bname}'",
                            database=bv_db,
                        ),
                    )
                    if not src_raw.get("error") and src_raw["rows"]:
                        for r in src_raw["rows"]:
                            source_tables.append(r)

                ds_details = []
                for ds_db, ds_name in datasources:
                    ds_raw = await loop.run_in_executor(
                        None,
                        lambda ddb=ds_db, dname=ds_name: _vql_query(
                            f'DESC VQL DATASOURCE JDBC "{ddb}"."{dname}"',
                            database=ddb,
                        ),
                    )
                    if not ds_raw.get("error") and ds_raw["rows"]:
                        vql_text = ds_raw["rows"][0].get("result", "")
                        info = {"name": ds_name, "database": ds_db, "vql_excerpt": ""}
                        for line in vql_text.split("\n"):
                            line = line.strip()
                            if any(k in line for k in ["DATABASEURI", "USERNAME", "DRIVERCLASSNAME"]):
                                info["vql_excerpt"] += line + "\n"
                        ds_details.append(info)

                result = {
                    "view": view,
                    "database": database,
                    "dependency_chain": chain,
                    "base_views": [{"database": db, "view": v} for db, v in base_views],
                    "source_tables": source_tables,
                    "datasources": ds_details,
                }

        elif name == "denodo_reverse_lineage":
            datasource = arguments["datasource"]

            ds_raw = await loop.run_in_executor(
                None,
                lambda: _vql_query(
                    f"SELECT database_name, name, subtype FROM GET_ELEMENTS() "
                    f"WHERE type = 'datasource' AND name = '{datasource}'"
                ),
            )
            if ds_raw.get("error"):
                result = ds_raw
            elif not ds_raw["rows"]:
                result = {
                    "error": True,
                    "details": {
                        "message": f"Datasource '{datasource}' not found. Use denodo_list_datasources to find valid names."
                    },
                }
            else:
                ds_db = ds_raw["rows"][0]["database_name"]
                ds_subtype = ds_raw["rows"][0]["subtype"]

                bv_raw = await loop.run_in_executor(
                    None,
                    lambda: _vql_query(
                        f"SELECT name, folder FROM GET_ELEMENTS() "
                        f"WHERE type = 'view' AND subtype = 'base' AND database_name = '{ds_db}' "
                        f"ORDER BY name",
                        database=ds_db,
                    ),
                )
                if bv_raw.get("error"):
                    result = bv_raw
                else:
                    all_base_views = bv_raw["rows"]

                    def _check_base_view(bv_name, folder):
                        dep = _vql_query(
                            f"SELECT dependency_name FROM VIEW_DEPENDENCIES('{ds_db}', '{bv_name}', 'false') "
                            f"WHERE dependency_name = '{datasource}'",
                            database=ds_db,
                            timeout=10,
                        )
                        if dep.get("error") or not dep["rows"]:
                            return None
                        src = _vql_query(
                            f"SELECT source_catalog_name, source_schema_name, source_table_name "
                            f"FROM GET_SOURCE_TABLE() "
                            f"WHERE input_database_name = '{ds_db}' AND input_view_name = '{bv_name}'",
                            database=ds_db,
                            timeout=10,
                        )
                        source_table = ""
                        if not src.get("error") and src["rows"]:
                            s = src["rows"][0]
                            source_table = f"{s['source_catalog_name']}.{s['source_schema_name']}.{s['source_table_name']}"
                        return {"base_view": bv_name, "database": ds_db, "folder": folder, "source_table": source_table}

                    from concurrent.futures import ThreadPoolExecutor
                    with ThreadPoolExecutor(max_workers=20) as pool:
                        futures = [
                            pool.submit(_check_base_view, bv["name"], bv["folder"])
                            for bv in all_base_views
                        ]
                        matching = [f.result() for f in futures if f.result() is not None]

                    result = {
                        "datasource": datasource,
                        "datasource_database": ds_db,
                        "datasource_type": ds_subtype,
                        "base_views_scanned": len(all_base_views),
                        "base_views_matched": len(matching),
                        "base_views": sorted(matching, key=lambda x: x["base_view"]),
                        "hint": "Use denodo_view_lineage with database and a base view name to trace its downstream consumers.",
                    }

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def main():
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
