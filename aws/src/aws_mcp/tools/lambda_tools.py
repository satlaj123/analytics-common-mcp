"""Lambda function monitoring tools."""
from datetime import datetime, timezone, timedelta


def list_functions(session_mgr, account="pipeline"):
    client = session_mgr.get_client("lambda", account)
    paginator = client.get_paginator("list_functions")
    functions = []
    for page in paginator.paginate():
        for fn in page["Functions"]:
            functions.append({
                "name": fn["FunctionName"],
                "runtime": fn.get("Runtime", "N/A"),
                "memory": fn.get("MemorySize", 0),
                "timeout": fn.get("Timeout", 0),
                "last_modified": fn.get("LastModified", ""),
            })

    functions.sort(key=lambda f: f["last_modified"], reverse=True)
    lines = [f"Found {len(functions)} Lambda functions:\n"]
    for fn in functions:
        lines.append(
            f"  {fn['name']:50} | {fn['runtime']:12} | {fn['memory']}MB | "
            f"timeout:{fn['timeout']}s | modified:{fn['last_modified'][:10]}"
        )
    return "\n".join(lines)


def get_function_details(session_mgr, function_name, account="pipeline"):
    client = session_mgr.get_client("lambda", account)
    fn = client.get_function(FunctionName=function_name)
    config = fn["Configuration"]
    env_vars = config.get("Environment", {}).get("Variables", {})

    lines = [
        f"Function: {config['FunctionName']}",
        f"  ARN: {config['FunctionArn']}",
        f"  Runtime: {config.get('Runtime', 'N/A')}",
        f"  Handler: {config.get('Handler', 'N/A')}",
        f"  Memory: {config.get('MemorySize', 0)} MB",
        f"  Timeout: {config.get('Timeout', 0)} seconds",
        f"  Last Modified: {config.get('LastModified', '')}",
        f"  Description: {config.get('Description', 'N/A')}",
    ]

    if env_vars:
        lines.append(f"\n  Environment Variables ({len(env_vars)}):")
        for key in sorted(env_vars.keys()):
            lines.append(f"    {key} = {env_vars[key][:50]}{'...' if len(env_vars[key]) > 50 else ''}")

    layers = config.get("Layers", [])
    if layers:
        lines.append(f"\n  Layers ({len(layers)}):")
        for layer in layers:
            lines.append(f"    {layer['Arn'].split(':')[-2]}")

    return "\n".join(lines)


def get_lambda_errors(session_mgr, function_name, hours=24, account="pipeline"):
    logs_client = session_mgr.get_client("logs", account)
    log_group = f"/aws/lambda/{function_name}"

    start_time = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp() * 1000)
    end_time = int(datetime.now(timezone.utc).timestamp() * 1000)

    try:
        resp = logs_client.filter_log_events(
            logGroupName=log_group,
            startTime=start_time,
            endTime=end_time,
            filterPattern="?ERROR ?Exception ?Traceback ?\\\"Task timed out\\\"",
            limit=50,
        )
    except logs_client.exceptions.ResourceNotFoundException:
        return f"No log group found for '{function_name}' (log group: {log_group})"

    events = resp.get("events", [])
    if not events:
        return f"No errors found in '{function_name}' logs (last {hours} hours)"

    lines = [f"Found {len(events)} error entries in '{function_name}' (last {hours}h):\n"]
    for event in events[:25]:
        ts = datetime.fromtimestamp(event["timestamp"] / 1000, tz=timezone.utc)
        msg = event["message"].strip()[:200]
        lines.append(f"  [{ts.strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

    if len(events) > 25:
        lines.append(f"\n  ... and {len(events) - 25} more entries")
    return "\n".join(lines)