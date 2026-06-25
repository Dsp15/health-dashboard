"""
analyze_recovery.py

Cross-references your Whoop sleep and recovery data to find patterns:
  - Does more sleep = better recovery?
  - Which days of the week do you recover best?
  - What does a "green day" look like for you personally?
  - How does HRV track with recovery score?

Run it:
    python src/analyze_recovery.py
"""

from whoop_client import WhoopClient
from datetime import datetime, timezone


# ── Helpers ────────────────────────────────────────────────────────────────────

def millis_to_hours(ms: int) -> float:
    return round(ms / 3_600_000, 1)

def format_date(iso_string: str) -> str:
    dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
    return dt.strftime("%b %d")

def day_of_week(iso_string: str) -> str:
    dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
    return dt.strftime("%A")  # e.g. "Monday"

def recovery_label(score: float) -> str:
    """Whoop color-codes recovery: green = 67+, yellow = 34-66, red = 0-33."""
    if score >= 67:
        return "🟢 Green"
    elif score >= 34:
        return "🟡 Yellow"
    else:
        return "🔴 Red"


# ── Join sleep + recovery data ─────────────────────────────────────────────────

def join_sleep_and_recovery(sleep_records: list, recovery_records: list) -> list:
    """
    Sleep and recovery come from separate API endpoints but share a cycle_id.
    This function joins them so we can look at both together for the same night.

    This is a common data engineering pattern — joining two datasets on a shared key.
    In a database you'd do this with a SQL JOIN.
    """
    # Build a lookup dict: cycle_id -> recovery record
    recovery_by_cycle = {
        r["cycle_id"]: r
        for r in recovery_records
        if r.get("score_state") == "SCORED"
    }

    joined = []
    for sleep in sleep_records:
        if sleep.get("score_state") != "SCORED" or sleep.get("nap"):
            continue
        cycle_id = sleep.get("cycle_id")
        recovery = recovery_by_cycle.get(cycle_id)
        if recovery:
            joined.append({
                "date": format_date(sleep["start"]),
                "day": day_of_week(sleep["start"]),
                "sleep_hours": millis_to_hours(sleep["score"]["stage_summary"]["total_in_bed_time_milli"]),
                "sleep_performance": sleep["score"].get("sleep_performance_percentage"),
                "recovery_score": recovery["score"].get("recovery_score"),
                "hrv": recovery["score"].get("hrv_rmssd_milli"),
                "resting_hr": recovery["score"].get("resting_heart_rate"),
            })

    return joined


# ── Analysis ───────────────────────────────────────────────────────────────────

def analyze(data: list) -> None:
    if not data:
        print("Not enough matched records to analyze.")
        return

    print(f"\nAnalyzing {len(data)} nights with matched sleep + recovery data\n")

    # ── Day-by-day table ──────────────────────────────────────────
    print("=" * 70)
    print(f"\n{'Date':<10} {'Day':<10} {'Sleep':>6} {'Sleep%':>7} {'Recovery':>9} {'HRV':>6} {'RHR':>5}")
    print(f"{'-'*10} {'-'*10} {'-'*6} {'-'*7} {'-'*9} {'-'*6} {'-'*5}")

    for d in data:
        rec = d["recovery_score"]
        print(
            f"{d['date']:<10} "
            f"{d['day']:<10} "
            f"{d['sleep_hours']:>5}h "
            f"{int(d['sleep_performance'] or 0):>6}% "
            f"{recovery_label(rec) if rec else 'n/a':>9} "
            f"{round(d['hrv'] or 0):>6} "
            f"{int(d['resting_hr'] or 0):>5}"
        )

    # ── Averages ──────────────────────────────────────────────────
    scores = [d["recovery_score"] for d in data if d["recovery_score"] is not None]
    hrvs   = [d["hrv"] for d in data if d["hrv"] is not None]
    rhrs   = [d["resting_hr"] for d in data if d["resting_hr"] is not None]
    sleep_perfs = [d["sleep_performance"] for d in data if d["sleep_performance"] is not None]

    print("\n" + "=" * 70)
    print("\n📊 AVERAGES")
    print(f"  Recovery score:     {round(sum(scores)/len(scores))}%")
    print(f"  HRV (RMSSD):        {round(sum(hrvs)/len(hrvs), 1)} ms")
    print(f"  Resting heart rate: {round(sum(rhrs)/len(rhrs))} bpm")
    print(f"  Sleep performance:  {round(sum(sleep_perfs)/len(sleep_perfs))}%")

    # ── Day of week patterns ──────────────────────────────────────
    print("\n📅 RECOVERY BY DAY OF WEEK")
    day_scores: dict[str, list] = {}
    for d in data:
        if d["recovery_score"] is not None:
            day_scores.setdefault(d["day"], []).append(d["recovery_score"])

    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for day in day_order:
        if day in day_scores:
            avg = sum(day_scores[day]) / len(day_scores[day])
            bar = "█" * int(avg / 5)  # simple text bar chart
            print(f"  {day:<10}  {round(avg):>3}%  {bar}")

    # ── Sleep vs recovery correlation ─────────────────────────────
    print("\n🔗 SLEEP DURATION vs RECOVERY")
    # Bucket nights by sleep duration
    buckets = {"< 6h": [], "6-7h": [], "7-8h": [], "8h+": []}
    for d in data:
        if d["recovery_score"] is None:
            continue
        h = d["sleep_hours"]
        if h < 6:
            buckets["< 6h"].append(d["recovery_score"])
        elif h < 7:
            buckets["6-7h"].append(d["recovery_score"])
        elif h < 8:
            buckets["7-8h"].append(d["recovery_score"])
        else:
            buckets["8h+"].append(d["recovery_score"])

    for label, scores_bucket in buckets.items():
        if scores_bucket:
            avg = round(sum(scores_bucket) / len(scores_bucket))
            n = len(scores_bucket)
            print(f"  {label:<6}  avg recovery: {avg}%  ({n} nights)")

    # ── What does YOUR green day look like? ───────────────────────
    green_days = [d for d in data if d["recovery_score"] and d["recovery_score"] >= 67]
    if green_days:
        avg_green_sleep = sum(d["sleep_hours"] for d in green_days) / len(green_days)
        avg_green_hrv   = sum(d["hrv"] for d in green_days if d["hrv"]) / len([d for d in green_days if d["hrv"]])
        print(f"\n🟢 YOUR GREEN DAY PROFILE ({len(green_days)} green days)")
        print(f"  Average sleep:  {round(avg_green_sleep, 1)}h")
        print(f"  Average HRV:    {round(avg_green_hrv, 1)} ms")

    print("\n" + "=" * 70)


# ── Entry Point ────────────────────────────────────────────────────────────────

def main():
    print("=== Recovery Analysis ===")

    client = WhoopClient()

    print("Fetching sleep data...")
    sleep_response = client.get_sleep_collection(limit=25)

    print("Fetching recovery data...")
    recovery_response = client.get_recovery_collection(limit=25)

    sleep_records    = sleep_response.get("records", [])
    recovery_records = recovery_response.get("records", [])

    print(f"Got {len(sleep_records)} sleep + {len(recovery_records)} recovery records.")

    data = join_sleep_and_recovery(sleep_records, recovery_records)
    analyze(data)


if __name__ == "__main__":
    main()
