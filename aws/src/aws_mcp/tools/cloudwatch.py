"""CloudWatch log search tools."""
from datetime import datetime, timezone, timedelta


def search_logs(session_mgr, log_group, filter_pattern="", hours=24, account="pipeline"):
    client = session_mgr.get_client("logs", account)
    start_time = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp() * 1000)
    end_time = int(datetime.now(timezone.utc).timestamp() * 1000)

    try:
        resp = client.filter_log_events(
            logGroupName=log_group,
            startTime=start_time,
            endTime=end_time,
            filterPattern=filter_pattern,
            limit=50,
        )
    except client.exceptions.ResourceNotFoundException:
        return f"Log group not found: {log_group}"

    events = resp.get("events", [])
    if not events:
        return f"No matching log events in '{log_group}' (last {hours}h, pattern: '{filter_pattern}')"

    lines = [f"Found {len(events)} events in '{log_group}' (last {hours}h):\\n"]
    for event in events[:30]:
        ts = datetime.fromtimestamp(event["timestamp"] / 1000, tz=timezone.utc)
        msg = event["message"].strip()[:200]
        lines.append(f"  [{ts.strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

    if len(events) > 30:
        lines.append(f"\\n  ... and {len(events) - 30} more entries")
    return "\\n".join(lines)


def list_log_groups(session_mgr, prefix="", account="pipeline"):
    client = session_mgr.get_client("logs", account)
    params = {}
    if prefix:
        params["logGroupNamePrefix"] = prefix

    paginator = client.get_paginator("describe_log_groups")
    groups = []
    for page in paginator.paginate(**params):
        for g in page["logGroups"]:
            groups.append({
                "name": g["logGroupName"],
                "stored_bytes": g.get("storedBytes", 0),
            })

    lines = [f"Found {len(groups)} log groups" + (f" (prefix: '{prefix}')" if prefix else "") + ":\\n"]
    for g in groups[:100]:
        size_mb = g["stored_bytes"] / (1024 * 1024)
        lines.append(f"  {g['name']:70} | {size_mb:.1f} MB")
    if len(groups) > 100:
        lines.append(f"\\n  ... and {len(groups) - 100} more")
    return "\\n".join(lines)


def get_step_function_logs(session_mgr, pipeline_name, hours=24, account="pipeline"):
    client = session_mgr.get_client("logs", account)
    log_group = f"/aws/states/{pipeline_name}"

    try:
        resp = client.filter_log_events(
            logGroupName=log_group,
            startTime=int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp() * 1000),
            endTime=int(datetime.now(timezone.utc).timestamp() * 1000),
            filterPattern="?ERROR ?error ?Error ?FAILED ?failed",
            limit=50,
        )
    except client.exceptions.ResourceNotFoundException:
        log_group_alt = f"/aws/vendedlogs/states/{pipeline_name}"
        try:
            resp = client.filter_log_events(
                logGroupName=log_group_alt,
                startTime=int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp() * 1000),
                endTime=int(datetime.now(timezone.utc).timestamp() * 1000),
                filterPattern="?ERROR ?error ?Error ?FAILED ?failed",
                limit=50,
            )
        except client.exceptions.ResourceNotFoundException:
            return f"No log group found for pipeline '{pipeline_name}' (tried {log_group} and {log_group_alt})"

    events = resp.get("events", [])
    if not events:
        return f"No error logs found for '{pipeline_name}' (last {hours}h)"

    lines = [f"Found {len(events)} error entries for '{pipeline_name}' (last {hours}h):\\n"]
    for event in events[:25]:
        ts = datetime.fromtimestamp(event["timestamp"] / 1000, tz=timezone.utc)
        msg = event["message"].strip()[:200]
        lines.append(f"  [{ts.strftime('%Y-%m-%d %H:%M:%S')}] {msg}")
    return "\\n".join(lines)