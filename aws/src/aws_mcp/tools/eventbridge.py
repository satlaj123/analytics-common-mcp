"""EventBridge schedules and triggers tools."""

def list_rules(session_mgr, account="pipeline"):
    client = session_mgr.get_client("events", account)
    paginator = client.get_paginator("list_rules")
    rules = []
    for page in paginator.paginate():
        for rule in page["Rules"]:
            rules.append({
                "name": rule["Name"],
                "state": rule["State"],
                "schedule": rule.get("ScheduleExpression", "event-pattern"),
                "description": rule.get("Description", "")
            })

    lines = [f"Found {len(rules)} EventBridge rules:\\n"]
    for r in sorted(rules, key=lambda x: x["name"]):
        state_icon = "ON " if r["state"] == "ENABLED" else "OFF"
        lines.append(f"  [{state_icon}] {r['name']:50} | {r['schedule']}")
    return "\\n".join(lines)


def get_rule_targets(session_mgr, rule_name, account="pipeline"):
    client = session_mgr.get_client("events", account)
    resp = client.list_targets_by_rule(Rule=rule_name)
    targets = resp.get("Targets", [])

    if not targets:
        return f"No targets found for rule '{rule_name}'"

    rule_resp = client.describe_rule(Name=rule_name)

    lines = [
        f"Rule: {rule_name}",
        f"  State: {rule_resp.get('State', 'UNKNOWN')}",
        f"  Schedule: {rule_resp.get('ScheduleExpression', 'event-pattern')}",
        f"  Description: {rule_resp.get('Description', 'N/A')}",
        f"\\n  Targets ({len(targets)}):"
    ]
    for t in targets:
        arn = t["Arn"]
        service = arn.split(":")[2] if ":" in arn else "unknown"
        name = arn.split(":")[-1] if ":" in arn else arn
        lines.append(f"    [{service}] {name}")
        if t.get("Input"):
            lines.append(f"      Input: {t['Input'][:100]}")
    return "\\n".join(lines)