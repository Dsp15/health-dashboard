"""
analyze_training.py

Combines Garmin activity data with Whoop recovery scores to analyze
triathlon training patterns and recovery.

Key questions answered:
  - How long did it take to recover after the half ironman?
  - Which sport types (swim/bike/run) hit recovery hardest?
  - What does your training load look like week by week?
  - How does Garmin Body Battery compare to Whoop recovery?

Run it:
    python src/analyze_training.py
"""

from garmin_client import GarminClient
from whoop_client import WhoopClient
from datetime import datetime, date, timedelta
from collections import defaultdict


# ── Helpers ────────────────────────────────────────────────────────────────────

def parse_date(iso_string: str) -> date:
    """Parse an ISO date string to a date object."""
    return datetime.fromisoformat(iso_string.replace("Z", "+00:00")).date()

def format_date(d: date) -> str:
    return d.strftime("%b %d")

def sport_label(type_key: str) -> str:
    """Clean up Garmin's sport type keys into readable labels."""
    labels = {
        "running":              "🏃 Run",
        "cycling":              "🚴 Bike",
        "open_water_swimming":  "🏊 Swim",
        "swimming":             "🏊 Swim",
        "strength_training":    "💪 Strength",
        "multi_sport":          "🏁 Triathlon",
        "road_biking":          "🚴 Bike",
        "treadmill_running":    "🏃 Run (treadmill)",
        "trail_running":        "🏃 Trail Run",
    }
    return labels.get(type_key, f"🏅 {type_key.replace('_', ' ').title()}")

def recovery_label(score) -> str:
    if score is None:
        return "  n/a"
    if score >= 67:
        return f"🟢 {int(score)}%"
    elif score >= 34:
        return f"🟡 {int(score)}%"
    else:
        return f"🔴 {int(score)}%"

def duration_str(seconds: float) -> str:
    if not seconds:
        return "n/a"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


# ── Data Loading ───────────────────────────────────────────────────────────────

def load_whoop_recovery(client: WhoopClient, start: str) -> dict:
    """
    Load Whoop recovery data and index it by date.
    Returns a dict: {date_string -> recovery_score}
    """
    records = client.get_all_recovery(start=start)
    by_date = {}
    for r in records:
        if r.get("score_state") != "SCORED":
            continue
        # Recovery is associated with the cycle's start (wake-up time)
        created = r.get("created_at", "")
        if created:
            d = parse_date(created).isoformat()
            by_date[d] = {
                "recovery_score": r["score"].get("recovery_score"),
                "hrv":            r["score"].get("hrv_rmssd_milli"),
                "resting_hr":     r["score"].get("resting_heart_rate"),
            }
    return by_date

def load_garmin_activities(client: GarminClient, start: str, end: str) -> list:
    """Load all Garmin activities in a date range."""
    activities = client.get_activities_by_date(start, end)
    parsed = []
    for a in activities:
        start_time = a.get("startTimeLocal", "")
        if not start_time:
            continue
        parsed.append({
            "date":        start_time[:10],
            "datetime":    start_time,
            "sport":       a.get("activityType", {}).get("typeKey", "unknown"),
            "duration_s":  a.get("duration", 0),
            "distance_m":  a.get("distance", 0),
            "avg_hr":      a.get("averageHR"),
            "max_hr":      a.get("maxHR"),
            "calories":    a.get("calories", 0),
            "name":        a.get("activityName", ""),
        })
    return sorted(parsed, key=lambda x: x["date"])

def load_garmin_body_battery(client: GarminClient, start: str, end: str) -> dict:
    """
    Load Garmin Body Battery data indexed by date.
    Fetches in 30-day chunks because the API rejects large date ranges.
    This is called chunked pagination — a common pattern when APIs have range limits.
    """
    by_date = {}
    current = datetime.strptime(start, "%Y-%m-%d").date()
    end_date = datetime.strptime(end, "%Y-%m-%d").date()

    while current <= end_date:
        chunk_end = min(current + timedelta(days=29), end_date)
        try:
            data = client.get_body_battery(current.isoformat(), chunk_end.isoformat())
            for d in data:
                by_date[d.get("date")] = {
                    "charged": d.get("charged"),
                    "drained": d.get("drained"),
                }
        except Exception as e:
            print(f"  Body battery chunk {current} to {chunk_end} failed: {e}")
        current = chunk_end + timedelta(days=1)

    return by_date


# ── Analysis ───────────────────────────────────────────────────────────────────

def analyze(activities: list, whoop: dict, body_battery: dict) -> None:

    # ── Activity Log with Recovery Context ───────────────────────
    print("\n📋 TRAINING LOG + RECOVERY IMPACT")
    print("=" * 80)
    print(f"\n{'Date':<8} {'Sport':<22} {'Duration':<9} {'AvgHR':<7} {'Whoop Rec':<11} {'Body Bat'}")
    print("-" * 80)

    for a in activities:
        d = a["date"]
        # Next day recovery (training affects next-day recovery)
        next_day = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        w = whoop.get(next_day, {})
        bb = body_battery.get(d, {})

        rec_str = recovery_label(w.get("recovery_score"))
        bb_str  = f"{bb.get('charged', 'n/a')} charged" if bb.get("charged") else "n/a"
        dist_km = round(a["distance_m"] / 1000, 1) if a["distance_m"] else None
        dist_str = f" {dist_km}km" if dist_km else ""

        print(
            f"{d[5:]:<8} "
            f"{sport_label(a['sport']):<22} "
            f"{duration_str(a['duration_s']):<9} "
            f"{int(a['avg_hr'] or 0):>4} bpm  "
            f"{rec_str:<11} "
            f"{bb_str}"
        )

    # ── Half Ironman Recovery Story ───────────────────────────────
    print("\n\n🏁 HALF IRONMAN RECOVERY STORY (Jun 14)")
    print("=" * 80)
    race_date = "2026-06-14"
    print(f"\n{'Days After Race':<18} {'Date':<10} {'Whoop Recovery':<16} {'HRV':<8} {'Body Battery'}")
    print("-" * 60)

    for i in range(10):
        d = (datetime.strptime(race_date, "%Y-%m-%d") + timedelta(days=i)).strftime("%Y-%m-%d")
        w  = whoop.get(d, {})
        bb = body_battery.get(d, {})
        label = "🏁 RACE DAY" if i == 0 else f"Day +{i}"
        rec = recovery_label(w.get("recovery_score"))
        hrv = f"{round(w.get('hrv', 0) or 0)} ms" if w.get("hrv") else "n/a"
        bb_str = f"{bb.get('charged', 'n/a')}" if bb.get("charged") else "n/a"
        print(f"  {label:<16} {d[5:]:<10} {rec:<16} {hrv:<8} {bb_str}")

    # ── Sport Type Breakdown ──────────────────────────────────────
    print("\n\n🏊🚴🏃 SPORT BREAKDOWN")
    print("=" * 80)
    sport_stats: dict = defaultdict(lambda: {"count": 0, "duration_s": 0, "recovery_scores": []})

    for a in activities:
        sport = a["sport"]
        next_day = (datetime.strptime(a["date"], "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        w = whoop.get(next_day, {})
        sport_stats[sport]["count"]        += 1
        sport_stats[sport]["duration_s"]   += a["duration_s"] or 0
        if w.get("recovery_score"):
            sport_stats[sport]["recovery_scores"].append(w["recovery_score"])

    print(f"\n  {'Sport':<22} {'Sessions':<10} {'Total Time':<12} {'Avg Next-Day Recovery'}")
    print(f"  {'-'*22} {'-'*10} {'-'*12} {'-'*20}")

    for sport, stats in sorted(sport_stats.items(), key=lambda x: -x[1]["duration_s"]):
        avg_rec = (sum(stats["recovery_scores"]) / len(stats["recovery_scores"])
                   if stats["recovery_scores"] else None)
        rec_str = f"{round(avg_rec)}%" if avg_rec else "n/a"
        print(
            f"  {sport_label(sport):<22} "
            f"{stats['count']:<10} "
            f"{duration_str(stats['duration_s']):<12} "
            f"{rec_str}"
        )

    # ── Weekly Training Load ──────────────────────────────────────
    print("\n\n📅 WEEKLY TRAINING LOAD")
    print("=" * 80)
    weeks: dict = defaultdict(lambda: {"activities": [], "recovery_scores": []})

    for a in activities:
        d = datetime.strptime(a["date"], "%Y-%m-%d")
        # Get the Monday of this week as the week key
        monday = (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")
        weeks[monday]["activities"].append(a)
        next_day = (d + timedelta(days=1)).strftime("%Y-%m-%d")
        w = whoop.get(next_day, {})
        if w.get("recovery_score"):
            weeks[monday]["recovery_scores"].append(w["recovery_score"])

    print(f"\n  {'Week of':<12} {'Sessions':<10} {'Total Time':<12} {'Sports':<30} {'Avg Recovery'}")
    print(f"  {'-'*12} {'-'*10} {'-'*12} {'-'*30} {'-'*12}")

    for monday in sorted(weeks.keys()):
        week = weeks[monday]
        acts = week["activities"]
        total_s = sum(a["duration_s"] or 0 for a in acts)
        sports = ", ".join(set(sport_label(a["sport"]) for a in acts))
        avg_rec = (sum(week["recovery_scores"]) / len(week["recovery_scores"])
                   if week["recovery_scores"] else None)
        rec_str = recovery_label(avg_rec) if avg_rec else "n/a"
        week_label = datetime.strptime(monday, "%Y-%m-%d").strftime("%b %d")
        print(
            f"  {week_label:<12} "
            f"{len(acts):<10} "
            f"{duration_str(total_s):<12} "
            f"{sports[:30]:<30} "
            f"{rec_str}"
        )

    # ── Garmin vs Whoop Comparison ────────────────────────────────
    print("\n\n⚖️  GARMIN BODY BATTERY vs WHOOP RECOVERY")
    print("=" * 80)
    print("\n  Both measure 'readiness' but use different algorithms.")
    print(f"\n  {'Date':<10} {'Body Battery':<15} {'Whoop Recovery'}")
    print(f"  {'-'*10} {'-'*15} {'-'*14}")

    matched = [(d, body_battery[d], whoop[d])
               for d in sorted(body_battery.keys())
               if d in whoop and body_battery[d].get("charged") and whoop[d].get("recovery_score")]

    for d, bb, w in matched[-14:]:  # last 2 weeks
        bb_val  = bb.get("charged", "n/a")
        rec_val = w.get("recovery_score")
        print(f"  {d[5:]:<10} {bb_val:<15} {recovery_label(rec_val)}")

    print("\n" + "=" * 80)


# ── Entry Point ────────────────────────────────────────────────────────────────

def main():
    print("=== Training + Recovery Analysis ===")

    garmin = GarminClient()
    whoop  = WhoopClient()

    START = "2026-04-01"
    END   = date.today().isoformat()

    print("Fetching Garmin activities...")
    activities = load_garmin_activities(garmin, START, END)

    print("Fetching Garmin Body Battery...")
    body_battery = load_garmin_body_battery(garmin, START, END)

    print("Fetching Whoop recovery data...")
    whoop_recovery = load_whoop_recovery(whoop, start=f"{START}T00:00:00.000Z")

    print(f"\nGot: {len(activities)} activities, "
          f"{len(body_battery)} body battery days, "
          f"{len(whoop_recovery)} Whoop recovery records\n")

    analyze(activities, whoop_recovery, body_battery)


if __name__ == "__main__":
    main()
