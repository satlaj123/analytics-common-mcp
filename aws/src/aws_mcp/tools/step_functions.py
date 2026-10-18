"""Step Functions pipeline monitoring tools."""
from datetime import datetime, timezone, timedelta


def list_pipelines(session_mgr, account="pipeline"):
    client = session_mgr.get_client("stepfunctions", account)
    paginator = client.get_paginator("list_state_machines")
    machines = []
    for page in paginator.paginate():
        for sm in page["stateMachines"]:
            machines.append({
                "name": sm["name"],
                "arn": sm["stateMachineArn"],
                "created": sm["creationDate"].isoformat(),
            })

    groups = {}
    for m in machines:
        prefix = m["name"].split("-")[0] if "-" in m["name"] else "ungrouped"
        groups.setdefault(prefix, []).append(m["name"])

    lines = [f"Found {len(machines)} state machines:\n"]
    for prefix, names in sorted(groups.items()):
        lines.append(f"  [{prefix}] ({len(names)})")
        for n in sorted(names):
            lines.append(f"    - {n}")
    return "\n".join(lines)


def get_pipeline_status(session_mgr, pipeline_name, account="pipeline"):
    client = session_mgr.get_client("stepfunctions", account)
    arn = _find_state_machine_arn(client, pipeline_name)
    if not arn:
        return f"No state machine found matching '{pipeline_name}'"

    resp = client.list_executions(stateMachineArn=arn, maxResults=5)
    executions = resp.get("executions", [])

    if not executions:
        return f"No executions found for '{pipeline_name}'"

    lines = [f"Last 5 executions for '{pipeline_name}':\n"]
    for ex in executions:
        status = ex["status"]
        start = ex["startDate"]
        stop = ex.get("stopDate")
        duration = ""
        if stop:
            dur = stop - start
            duration = f" ({dur.total_seconds():.0f}s)"
        lines.append(f"  {status:10} | {start.strftime('%Y-%m-%d %H:%M')} {duration}")
    return "\n".join(lines)


def get_pipeline_history(session_mgr, pipeline_name, days=7, account="pipeline"):
    client = session_mgr.get_client("stepfunctions", account)
    arn = _find_state_machine_arn(client, pipeline_name)
    if not arn:
        return f"No state machine found matching '{pipeline_name}'"

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    executions = []
    paginator = client.get_paginator("list_executions")
    for page in paginator.paginate(stateMachineArn=arn):
        for ex in page["executions"]:
            if ex["startDate"] < cutoff:
                break
            executions.append(ex)
        else:
            continue
        break

    if not executions:
        return f"No executions in the last {days} days for '{pipeline_name}'"

    succeeded = sum(1 for e in executions if e["status"] == "SUCCEEDED")
    failed = sum(1 for e in executions if e["status"] == "FAILED")
    total = len(executions)
    rate = (succeeded / total * 100) if total else 0

    lines = [
        f"History for '{pipeline_name}' (last {days} days):",
        f"  Total: {total} | Succeeded: {succeeded} | Failed: {failed} | Success rate: {rate:.0f}%",
        "",
    ]
    for ex in executions[:20]:
        status = ex["status"]
        start = ex["startDate"].strftime("%Y-%m-%d %H:%M")
        lines.append(f"  {status:10} | {start}")
    if len(executions) > 20:
        lines.append(f"  ... and {len(executions) - 20} more")
    return "\n".join(lines)


def get_execution_details(session_mgr, execution_arn, account="pipeline"):
    client = session_mgr.get_client("stepfunctions", account)
    desc = client.describe_execution(executionArn=execution_arn)
    history = client.get_execution_history(executionArn=execution_arn, reverseOrder=True, maxResults=50)

    lines = [
        f"Execution: {desc['name']}",
        f"  Status: {desc['status']}",
        f"  Started: {desc['startDate'].isoformat()}",
    ]
    if "stopDate" in desc:
        lines.append(f"  Stopped: {desc['stopDate'].isoformat()}")

    errors = []
    for event in history.get("events", []):
        etype = event["type"]
        if "Failed" in etype or "Error" in etype:
            detail = event.get(
                next((k for k in event if k.endswith("EventDetails")), ""), {}
            )
            if isinstance(detail, dict):
                cause = detail.get("cause", detail.get("error", str(detail)))
            else:
                cause = str(detail)
            errors.append(f"  [{etype}] {cause[:200]}")

    if errors:
        lines.append("\nErrors:")
        lines.extend(errors[:10])
    return "\n".join(lines)


def _find_state_machine_arn(client, name):
    paginator = client.get_paginator("list_state_machines")
    name_lower = name.lower()
    for page in paginator.paginate():
        for sm in page["stateMachines"]:
            if name_lower in sm["name"].lower():
                return sm["stateMachineArn"]
    return None