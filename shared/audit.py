"""Shared audit logger for MCP servers — per-server JSON Lines log files with 15-day retention."""

import json
import os
import time
import getpass
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import contextmanager

LOG_DIR = Path(__file__).parent.parent / "logs"
RETENTION_DAYS = 15
_cleanup_done = set()


def _ensure_log_dir():
    LOG_DIR.mkdir(exist_ok=True)


def _cleanup_old_entries(log_file: Path, server: str):
    """Remove entries older than RETENTION_DAYS. Runs once per server per process."""
    if server in _cleanup_done or not log_file.exists():
        _cleanup_done.add(server)
        return
    _cleanup_done.add(server)

    cutoff = (datetime.now() - timedelta(days=RETENTION_DAYS)).isoformat()
    try:
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        kept = [
            ln for ln in lines
            if ln.strip() and json.loads(ln).get("timestamp", "") >= cutoff
        ]
        log_file.write_text("\n".join(kept) + "\n" if kept else "", encoding="utf-8")
    except Exception:
        pass


@contextmanager
def audit_tool_call(server: str, tool: str, arguments: dict):
    """Context manager that logs a tool call with timing to a per-server log file.

    Usage:
        with audit_tool_call("snowflake", "query_snowflake", args) as audit:
            result = do_the_work()
            audit.set_result(record_count=5)
    """
    entry = _AuditEntry(server, tool, arguments)
    try:
        yield entry
    except Exception as e:
        entry.set_error(str(e))
        raise
    finally:
        entry.write()


class _AuditEntry:
    def __init__(self, server, tool, arguments):
        self.server = server
        self.tool = tool
        self.arguments = _sanitize_args(arguments)
        self.start = time.time()
        self.record_count = None
        self.status = "success"
        self.error = None

    def set_result(self, record_count=None):
        self.record_count = record_count

    def set_error(self, error):
        self.status = "error"
        self.error = str(error)[:200]

    def write(self):
        duration_ms = int((time.time() - self.start) * 1000)
        entry = {
            "timestamp": datetime.now().isoformat(),
            "user": getpass.getuser(),
            "server": self.server,
            "tool": self.tool,
            "arguments": self.arguments,
            "status": self.status,
            "duration_ms": duration_ms,
        }
        if self.record_count is not None:
            entry["record_count"] = self.record_count
        if self.error:
            entry["error"] = self.error

        try:
            _ensure_log_dir()
            log_file = LOG_DIR / f"{self.server}.jsonl"
            _cleanup_old_entries(log_file, self.server)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception:
            pass


def _sanitize_args(arguments: dict) -> dict:
    """Keep argument keys and short values, truncate long ones. Never log passwords or tokens."""
    if not arguments:
        return {}
    sanitized = {}
    sensitive_keys = {"password", "token", "secret", "credential", "auth"}
    for k, v in arguments.items():
        if any(s in k.lower() for s in sensitive_keys):
            sanitized[k] = "***"
        elif isinstance(v, str) and len(v) > 100:
            sanitized[k] = v[:100] + "..."
        else:
            sanitized[k] = v
    return sanitized
