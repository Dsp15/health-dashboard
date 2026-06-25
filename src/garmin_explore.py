"""
garmin_explore.py

Quick exploration script to see what Garmin data looks like.
Run this first to understand what's available before building analysis.

Run it:
    python src/garmin_explore.py
"""

import json
from datetime import date, timedelta
from garmin_client import GarminClient

def pretty(data):
    print(json.dumps(data, indent=2, default=str))

def main():
    print("=== Garmin Data Explorer ===\n")

    client = GarminClient()

    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    # ── Daily Stats ───────────────────────────────────────────────
    print("── Daily Stats (yesterday) ──────────────────────────")
    try:
        stats = client.get_daily_stats(yesterday)
        # Pull out the most interesting fields
        print(f"  Steps:          {stats.get('totalSteps', 'n/a')}")
        print(f"  Active calories:{stats.get('activeKilocalories', 'n/a')}")
        print(f"  Resting HR:     {stats.get('restingHeartRate', 'n/a')}")
        print(f"  Stress (avg):   {stats.get('averageStressLevel', 'n/a')}")
        print(f"  Body Battery:   {stats.get('bodyBatteryMostRecentValue', 'n/a')}")
        print(f"  Floors:         {stats.get('floorsAscended', 'n/a')}")
    except Exception as e:
        print(f"  Error: {e}")

    # ── Sleep ─────────────────────────────────────────────────────
    print("\n── Sleep (last night) ───────────────────────────────")
    try:
        sleep = client.get_sleep(yesterday)
        daily = sleep.get("dailySleepDTO", {})
        print(f"  Sleep score:    {daily.get('sleepScores', {}).get('overall', {}).get('value', 'n/a')}")
        print(f"  Total sleep:    {round(daily.get('sleepTimeSeconds', 0) / 3600, 1)}h")
        print(f"  Deep sleep:     {round(daily.get('deepSleepSeconds', 0) / 3600, 1)}h")
        print(f"  REM sleep:      {round(daily.get('remSleepSeconds', 0) / 3600, 1)}h")
        print(f"  Light sleep:    {round(daily.get('lightSleepSeconds', 0) / 3600, 1)}h")
        print(f"  Awake:          {round(daily.get('awakeSleepSeconds', 0) / 3600, 1)}h")
        print(f"  Avg respiration:{daily.get('averageRespirationValue', 'n/a')}")
        print(f"  Avg SpO2:       {daily.get('averageSpO2Value', 'n/a')}")
    except Exception as e:
        print(f"  Error: {e}")

    # ── HRV ───────────────────────────────────────────────────────
    print("\n── HRV Status ───────────────────────────────────────")
    try:
        hrv = client.get_hrv_data(yesterday)
        summary = hrv.get("hrvSummary", {})
        print(f"  HRV (weekly avg): {summary.get('weeklyAvg', 'n/a')} ms")
        print(f"  Last night HRV:   {summary.get('lastNight', 'n/a')} ms")
        print(f"  HRV status:       {summary.get('status', 'n/a')}")
    except Exception as e:
        print(f"  Error: {e}")

    # ── Body Battery ──────────────────────────────────────────────
    print("\n── Body Battery (last 7 days) ───────────────────────")
    try:
        start = (date.today() - timedelta(days=7)).isoformat()
        bb = client.get_body_battery(start, today)
        for day in bb[-7:]:
            print(f"  {day.get('date', 'n/a')}: "
                  f"charged to {day.get('charged', 'n/a')}, "
                  f"drained to {day.get('drained', 'n/a')}")
    except Exception as e:
        print(f"  Error: {e}")

    # ── Recent Activities ─────────────────────────────────────────
    print("\n── Recent Activities ────────────────────────────────")
    try:
        activities = client.get_activities(start=0, limit=5)
        for a in activities:
            duration_min = round(a.get("duration", 0) / 60)
            print(f"  {a.get('startTimeLocal', 'n/a')[:10]}  "
                  f"{a.get('activityType', {}).get('typeKey', 'unknown'):<20} "
                  f"{duration_min} min  "
                  f"avg HR: {a.get('averageHR', 'n/a')}")
    except Exception as e:
        print(f"  Error: {e}")

    # ── Training Readiness ────────────────────────────────────────
    print("\n── Training Readiness ───────────────────────────────")
    try:
        tr = client.get_training_readiness(yesterday)
        # API returns a list — take the first item
        if isinstance(tr, list) and tr:
            tr = tr[0]
        print(f"  Score: {tr.get('score', 'n/a')}")
        print(f"  Level: {tr.get('level', 'n/a')}")
    except Exception as e:
        print(f"  Error: {e}")

    print("\nDone! Use this to decide which data streams to include in analysis.")

if __name__ == "__main__":
    main()
