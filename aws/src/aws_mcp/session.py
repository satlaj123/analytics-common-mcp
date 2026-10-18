"""Boto3 session management for AWS MCP."""

import boto3


class SessionManager:
    def __init__(self, config):
        self.config = config
        self._sessions = {}

    def _get_session(self, account_key):
        if account_key not in self._sessions:
            account = self.config["accounts"].get(account_key,{})
            profile = account.get("profile","")
            if not profile:
                raise ValueError(
                    f"The '{account_key}' account is not configured. "
                    f"To configure it, add AWS_{account_key.upper()}_* enviornment variables."
                )
            self._sessions[account_key] = boto3.Session(profile_name=profile)
        return self._sessions[account_key]

    def get_client(self, service, account_key="pipeline"):
        account = self.config["accounts"].get(account_key,{})
        if not account.get("profile"):
            raise ValueError(f"The '{account_key}' account is not configured.")

        if not account.get("profile"):
            raise ValueError(
                f"The '{account_key}' account is not configured. "
                f"To configure it, add AWS_{account_key.upper()}_* environment variables."
            )

        session = self._get_session(account_key)
        region = account.get("region", "us-east-2")
        return session.client(service, region_name=region)

    def is_account_configured(self, account_key):
        account = self.config["accounts"].get(account_key,{})
        return bool(account.get("profile"))
