"""DMS data replication monitoring tools."""

def list_replication_tasks(session_mgr, account="dms"):
    client = session_mgr.get_client("dms", account)
    resp = client.describe_replication_tasks()
    tasks = resp.get("ReplicationTasks", [])

    if not tasks:
        return "No DMS replication tasks found."

    lines = [f"Found {len(tasks)} DMS replication tasks:\n"]
    for t in tasks:
        status = t.get("Status", "unknown")
        name = t.get("ReplicationTaskIdentifier", "unnamed")
        migration_type = t.get("MigrationType", "")
        table_stats = t.get("ReplicationTaskStats", {})
        tables_loaded = table_stats.get("TablesLoaded", 0)
        lines.append(
            f"  {status:12} | {name:50} | type: {migration_type} | tables: {tables_loaded}"
        )
    return "\n".join(lines)


def get_replication_stats(session_mgr, task_identifier="", account="dms"):
    client = session_mgr.get_client("dms", account)

    params = {}
    if task_identifier:
        params["Filters"] = [{"Name": "replication-task-id", "Values": [task_identifier]}]

    resp = client.describe_replication_tasks(**params)
    tasks = resp.get("ReplicationTasks", [])

    if not tasks:
        return f"No replication task found matching '{task_identifier}'"

    lines = []
    for t in tasks:
        name = t.get("ReplicationTaskIdentifier", "unnamed")
        status = t.get("Status", "unknown")
        stats = t.get("ReplicationTaskStats", {})

        lines.append(f"Task: {name}")
        lines.append(f"  Status: {status}")
        lines.append(f"  Tables loaded: {stats.get('TablesLoaded', 0)}")
        lines.append(f"  Tables loading: {stats.get('TablesLoading', 0)}")
        lines.append(f"  Tables errored: {stats.get('TablesErrored', 0)}")
        lines.append(f"  CDC latency (source): {stats.get('CDCLatencySource', 0)}s")
        lines.append(f"  CDC latency (target): {stats.get('CDCLatencyTarget', 0)}s")

        if t.get("LastFailureMessage"):
            lines.append(f"  Last error: {t['LastFailureMessage'][:200]}")
        lines.append("")
    return "\n".join(lines)


def list_endpoints(session_mgr, account="dms"):
    client = session_mgr.get_client("dms", account)
    resp = client.describe_endpoints()
    endpoints = resp.get("Endpoints", [])

    if not endpoints:
        return "No DMS endpoints found."

    lines = [f"Found {len(endpoints)} DMS endpoints:\n"]
    for ep in sorted(endpoints, key=lambda x: x.get("EndpointIdentifier", "")):
        name = ep.get("EndpointIdentifier", "unnamed")
        ep_type = ep.get("EndpointType", "")
        engine = ep.get("EngineName", "")
        server = ep.get("ServerName", "")
        db = ep.get("DatabaseName", "")
        lines.append(f"  [{ep_type:6}] {name:40} | {engine:12} | {server}/{db}")
    return "\n".join(lines)