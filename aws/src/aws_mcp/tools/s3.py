"""S3 data verification tools."""
from datetime import datetime, timezone, timedelta


def list_buckets(session_mgr, account="pipeline"):
    client = session_mgr.get_client("s3", account)
    resp = client.list_buckets()
    buckets = resp.get("Buckets", [])

    lines = [f"Found {len(buckets)} S3 buckets:\n"]
    for b in sorted(buckets, key=lambda x: x["Name"]):
        created = b["CreationDate"].strftime("%Y-%m-%d")
        lines.append(f"  {b['Name']:60} | created: {created}")
    return "\n".join(lines)


def check_file_exists(session_mgr, bucket, key, account="pipeline"):
    client = session_mgr.get_client("s3", account)
    try:
        resp = client.head_object(Bucket=bucket, Key=key)
        size = resp["ContentLength"]
        modified = resp["LastModified"].isoformat()
        size_str = _format_size(size)
        return (
            f"File EXISTS:\n"
            f"  Bucket: {bucket}\n"
            f"  Key: {key}\n"
            f"  Size: {size_str}\n"
            f"  Last Modified: {modified}"
        )
    except client.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return f"File NOT FOUND: s3://{bucket}/{key}"
        raise


def list_recent_files(session_mgr, bucket, prefix="", hours=24, account="pipeline"):
    client = session_mgr.get_client("s3", account)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    paginator = client.get_paginator("list_objects_v2")
    params = {"Bucket": bucket}
    if prefix:
        params["Prefix"] = prefix

    recent = []
    for page in paginator.paginate(**params):
        for obj in page.get("Contents", []):
            if obj["LastModified"] >= cutoff:
                recent.append(obj)

    recent.sort(key=lambda x: x["LastModified"], reverse=True)

    if not recent:
        return f"No files modified in the last {hours} hours in s3://{bucket}/{prefix}"

    lines = [f"Found {len(recent)} files modified in the last {hours}h in s3://{bucket}/{prefix}:\n"]
    for obj in recent[:50]:
        modified = obj["LastModified"].strftime("%Y-%m-%d %H:%M")
        size_str = _format_size(obj["Size"])
        lines.append(f"  {modified} | {size_str:>8} | {obj['Key']}")

    if len(recent) > 50:
        lines.append(f"\n  ... and {len(recent) - 50} more files")
    return "\n".join(lines)


def list_prefixes(session_mgr, bucket, prefix="", account="pipeline"):
    client = session_mgr.get_client("s3", account)
    resp = client.list_objects_v2(Bucket=bucket, Prefix=prefix, Delimiter="/")

    folders = [p["Prefix"] for p in resp.get("CommonPrefixes", [])]
    files = resp.get("Contents", [])

    lines = [f"Contents of s3://{bucket}/{prefix}:\n"]
    if folders:
        lines.append(f"  Folders ({len(folders)}):")
        for f in sorted(folders):
            lines.append(f"    {f}")
    if files:
        lines.append(f"\n  Files ({len(files)}):")
        for obj in sorted(files, key=lambda x: x["Key"])[:30]:
            size_str = _format_size(obj["Size"])
            lines.append(f"    {size_str:>8} | {obj['Key']}")
        if len(files) > 30:
            lines.append(f"    ... and {len(files) - 30} more")
    return "\n".join(lines)


def _format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"