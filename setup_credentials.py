#!/usr/bin/env python3
"""
MCP Credential Manager — stores and verifies secrets in Windows Credential Manager.

Usage:
    python setup_credentials.py
    python setup_credentials.py --verify    # Check all credentials are set (exit code 0/1)
    python setup_credentials.py --set KEY   # Set a specific credential by key name
    python setup_credentials.py --list      # List all credential keys
"""

import argparse
import getpass
import sys

import keyring

# Registry of all managed credentials
CREDENTIALS = [
    {
        "key": "github-pat",
        "service": "mcp-github",
        "username": "personal_access_token",
        "label": "GitHub Personal Access Token",
        "server": "github",
    },
    {
        "key": "atlassian-secret",
        "service": "mcp-atlassian",
        "username": "client_secret",
        "label": "Atlassian OAuth Client Secret",
        "server": "jira + confluence",
    },
    {
        "key": "denodo-password",
        "service": "mcp-denodo",
        "username": "password",
        "label": "Denodo Password",
        "server": "denodo",
    },
    {
        "key": "dbt-token",
        "service": "mcp-dbt",
        "username": "api_token",
        "label": "dbt Cloud API Token",
        "server": "dbt",
    },
    {
        "key": "servicenow-secret",
        "service": "mcp-servicenow",
        "username": "client_secret",
        "label": "ServiceNow Client Secret",
        "server": "servicenow",
    },
    {
        "key": "powerbi-secret",
        "service": "mcp-powerbi-rest",
        "username": "client_secret",
        "label": "Power BI REST Client Secret",
        "server": "powerbi-rest",
    },
]


def mask(value: str) -> str:
    """Mask a credential value, showing only the first 8 chars."""
    if not value:
        return "(not set)"
    if len(value) <= 10:
        return value[:3] + "***"
    return value[:8] + "..."


def show_status() -> bool:
    """Show the status of all managed credentials."""
    print("MCP Credential Status")
    print("=" * 60)
    all_ok = True
    for cred in CREDENTIALS:
        value = keyring.get_password(cred["service"], cred["username"])
        status = mask(value) if value else "MISSING"
        print(f"{cred['key']:<25} {cred['label']:<35} {status}")
        if not value:
            all_ok = False
    print()
    return all_ok


def verify() -> bool:
    """Check all credentials are set. Returns True if all are present."""
    missing = []
    for cred in CREDENTIALS:
        value = keyring.get_password(cred["service"], cred["username"])
        if not value:
            missing.append(cred)

    if not missing:
        print("All credentials are set.")
        return True

    print(f"Missing {len(missing)} credential(s):")
    for cred in missing:
        print(f" - {cred['key']} [{cred['label']}]")
    return False


def set_credential(key: str) -> None:
    """Set a specific credential by key name."""
    cred = next((c for c in CREDENTIALS if c["key"] == key), None)
    if cred is None:
        print(f"Unknown credential key: {key}")
        print("Valid keys:")
        for item in CREDENTIALS:
            print(f"  - {item['key']}")
        sys.exit(1)

    current = keyring.get_password(cred["service"], cred["username"])
    print(f"Setting: {cred['label']}")
    print(f"Current: {mask(current)}")
    value = getpass.getpass("New value (enter to skip): ")
    if not value.strip():
        print("Skipped.")
        return

    keyring.set_password(cred["service"], cred["username"], value.strip())
    print("Saved.")


def interactive() -> None:
    """Show status and prompt to update each credential."""
    all_ok = show_status()
    if all_ok:
        print("All credentials are configured. Update any? (Y/n)", end=" ")
        answer = input().strip().lower()
        if answer == "n":
            return
    else:
        print("Some credentials are missing. Set them now? (Y/n)", end=" ")
        answer = input().strip().lower()
        if answer == "n":
            return

    print()
    for cred in CREDENTIALS:
        current = keyring.get_password(cred["service"], cred["username"])
        print(f"{cred['key']}: {cred['label']}")
        print(f"Current: {mask(current)}")
        value = getpass.getpass("New value (Enter to skip): ")
        if value.strip():
            keyring.set_password(cred["service"], cred["username"], value.strip())
            print("Updated.")
        else:
            print("Skipped.")
        print()

    print("Done. Final status:")
    show_status()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage MCP server credentials in Windows Credential Manager"
    )
    parser.add_argument("--verify", action="store_true", help="Verify all credentials are set")
    parser.add_argument("--set", metavar="KEY", help="Set a specific credential by key name")
    parser.add_argument("--list", action="store_true", help="List all credential keys")
    parser.add_argument("--interactive", action="store_true", help="Show status and prompt to update each credential")
    args = parser.parse_args()

    if args.list:
        for cred in CREDENTIALS:
            print(f"{cred['key']}: {cred['label']}")
        return

    if args.verify:
        ok = verify()
        sys.exit(0 if ok else 1)

    if args.set:
        set_credential(args.set)
        return

    if args.interactive:
        interactive()
        return

    interactive()


if __name__ == "__main__":
    main()
