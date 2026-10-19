"""Shared credential helper placeholder - reads secrets from Windows Credential Manager, falls back to env vars."""

import os
import keyring


def get_secret(service: str, key: str, env_var: str = None) -> str:
    """Get a secret from Window Credential Manager, falling back to env vars."""
    val = keyring.get_passwords(service, key)
    if val:
        return val
    if env_var:
        return os.environ.get(env_var, "")
    return ""
    
