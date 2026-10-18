# Load configuration from environment variables.
import os


def load_config():
    return {
        "sso_start_url": os.environ.get("AWS_SSO_START_URL", ""),
        "sso_region": os.environ.get("AWS_SSO_REGION", "us-east-1"),
        "accounts": {
            "pipeline": {
                "account_id": os.environ.get("AWS_PIPELINE_ACCOUNT_ID", ""),
                "role_name": os.environ.get("AWS_PIPELINE_ROLE_NAME", ""),
                "region": os.environ.get("AWS_PIPELINE_REGION", "us-east-2"),
                "profile": os.environ.get("AWS_PIPELINE_PROFILE", ""),
            },
            "dms": {
                "account_id": os.environ.get("AWS_DMS_ACCOUNT_ID", ""),
                "role_name": os.environ.get("AWS_DMS_ROLE_NAME", ""),
                "region": os.environ.get("AWS_DMS_REGION", "us-east-1"),
                "profile": os.environ.get("AWS_DMS_PROFILE", ""),
            },
            "dev": {
                "account_id": os.environ.get("AWS_DEV_ACCOUNT_ID", ""),
                "role_name": os.environ.get("AWS_DEV_ROLE_NAME", ""),
                "region": os.environ.get("AWS_DEV_REGION", "us-east-2"),
                "profile": os.environ.get("AWS_DEV_PROFILE", ""),
            },
        },
        "tool_timeout": int(os.environ.get("AWS_TOOL_TIMEOUT", "120")),
        "default_log_hours": int(os.environ.get("DEFAULT_LOG_HOURS", "24")),
        "default_history_days": int(os.environ.get("DEFAULT_HISTORY_DAYS", "7")),
    }
