"""
main.py — Entry point for the health dashboard.

Run this file to pull your latest data from Whoop:
    python src/main.py
"""

import json
from whoop_client import WhoopClient


def pretty(data: dict | list):
    """Print data as readable JSON — useful while exploring the API."""
    print(json.dumps(data, indent=2))


def main():
    print("=== Health Dashboard ===\n")

    # Initialize the client — this handles authentication automatically
    client = WhoopClient()

    # Get your profile
    print("── Profile ─────────────────────────")
    profile = client.get_profile()
    pretty(profile)

    # Get your 7 most recent recovery scores
    print("\n── Last 7 Recovery Scores ──────────")
    recovery = client.get_recovery_collection(limit=7)
    pretty(recovery)

    # Get your 7 most recent sleep records
    print("\n── Last 7 Sleep Records ────────────")
    sleep = client.get_sleep_collection(limit=7)
    pretty(sleep)

    print("\nDone! Next steps: pipe this data into a spreadsheet or dashboard.")


if __name__ == "__main__":
    main()
