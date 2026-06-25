"""
analyze_sleep.py

Pulls your last 30 days of Whoop sleep data and breaks it down:
  - How much time you spend in each sleep stage (light, REM, deep)
  - Your average sleep performance score
  - Your best and worst nights
  - A night-by-night summary table

Run it:
    python src/analyze_sleep.py
"""

from whoop_client import WhoopClient


# ── Helpers ────────────────────────────────────────────────────────────────────

def millis_to_hours(ms: int) -> float:
    """Convert milliseconds to hours, rounded to 1 decimal place."""
    return round(ms / 3_600_000, 1)

def millis_to_minutes(ms: int) -> float:
    """Convert milliseconds to minutes, rounded to 1 decimal place."""
    return round(ms / 60_000, 1)

def format_date(iso_string: str) -> str:
    """Turn '2026-06-20T03:12:00.000Z' into something readable like 'Jun 20'."""
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
    return dt.strftime("%b %d")


# ── Main Analysis ──────────────────────────────────────────────────────────────

def analyze_sleep(records: list) -> None:
    """
    Takes a list of sleep records from the Whoop API and prints a full analysis.

    Each record has a 'score' dict with stage_summary, performance percentages, etc.
    We skip any records that weren't scored (e.g. if the device lost data).
    """

    # Filter to only scored nights and exclude naps
    nights = [
        r for r in records
        if r.get("score_state") == "SCORED" and not r.get("nap", False)
    ]

    if not nights:
        print("No scored sleep records found.")
        return

    print(f"\nAnalyzing {len(nights)} nights of sleep data\n")
    print("=" * 60)

    # ── Night-by-Night Table ───────────────────────────────────────
    print(f"\n{'Date':<10} {'Total':>7} {'Light':>7} {'REM':>7} {'Deep':>7} {'Perf':>6}")
    print(f"{'-'*10} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*6}")

    total_light = total_rem = total_deep = total_in_bed = 0
    performance_scores = []
    best_night = worst_night = None

    for night in nights:
        score = night.get("score", {})
        stages = score.get("stage_summary", {})
        perf = score.get("sleep_performance_percentage")
        date = format_date(night["start"])

        in_bed   = stages.get("total_in_bed_time_milli", 0)
        light    = stages.get("total_light_sleep_time_milli", 0)
        rem      = stages.get("total_rem_sleep_time_milli", 0)
        deep     = stages.get("total_slow_wave_sleep_time_milli", 0)  # SWS = deep sleep

        # Accumulate totals for averages later
        total_in_bed += in_bed
        total_light  += light
        total_rem    += rem
        total_deep   += deep

        if perf is not None:
            performance_scores.append((perf, night))
            if best_night is None or perf > best_night[0]:
                best_night = (perf, night)
            if worst_night is None or perf < worst_night[0]:
                worst_night = (perf, night)

        perf_str = f"{int(perf)}%" if perf is not None else "n/a"
        print(
            f"{date:<10} "
            f"{millis_to_hours(in_bed):>6}h "
            f"{millis_to_hours(light):>6}h "
            f"{millis_to_hours(rem):>6}h "
            f"{millis_to_hours(deep):>6}h "
            f"{perf_str:>6}"
        )

    # ── Averages ───────────────────────────────────────────────────
    n = len(nights)
    avg_in_bed = total_in_bed / n
    avg_light  = total_light / n
    avg_rem    = total_rem / n
    avg_deep   = total_deep / n
    avg_perf   = sum(p for p, _ in performance_scores) / len(performance_scores) if performance_scores else 0

    # Sleep stage percentages (of total sleep time, not in-bed time)
    total_sleep = total_light + total_rem + total_deep
    pct_light = round(total_light / total_sleep * 100) if total_sleep else 0
    pct_rem   = round(total_rem   / total_sleep * 100) if total_sleep else 0
    pct_deep  = round(total_deep  / total_sleep * 100) if total_sleep else 0

    print("\n" + "=" * 60)
    print("\n📊 AVERAGES")
    print(f"  Time in bed:        {millis_to_hours(avg_in_bed)}h")
    print(f"  Light sleep:        {millis_to_hours(avg_light)}h  ({pct_light}% of sleep)")
    print(f"  REM sleep:          {millis_to_hours(avg_rem)}h  ({pct_rem}% of sleep)")
    print(f"  Deep sleep:         {millis_to_hours(avg_deep)}h  ({pct_deep}% of sleep)")
    print(f"  Sleep performance:  {round(avg_perf)}%")

    # ── Context: what do these numbers mean? ──────────────────────
    print("\n💡 WHAT THIS MEANS")
    print("  Healthy sleep stage targets (approximate):")
    print("    Light: 45-55%  |  REM: 20-25%  |  Deep: 15-25%")
    print(f"  Your split:  Light {pct_light}%  |  REM {pct_rem}%  |  Deep {pct_deep}%")

    if pct_deep < 15:
        print("  ⚠️  Your deep sleep is on the low side. Deep sleep is when your")
        print("      body repairs muscle and consolidates memory.")
    if pct_rem < 20:
        print("  ⚠️  Your REM sleep is on the low side. REM is tied to emotional")
        print("      processing and cognitive performance.")

    # ── Best and Worst Nights ─────────────────────────────────────
    if best_night:
        b_score, b_night = best_night
        b_stages = b_night["score"]["stage_summary"]
        print(f"\n🏆 BEST NIGHT — {format_date(b_night['start'])} ({int(b_score)}% performance)")
        print(f"   {millis_to_hours(b_stages['total_in_bed_time_milli'])}h in bed  |  "
              f"{millis_to_hours(b_stages['total_rem_sleep_time_milli'])}h REM  |  "
              f"{millis_to_hours(b_stages['total_slow_wave_sleep_time_milli'])}h deep")

    if worst_night:
        w_score, w_night = worst_night
        w_stages = w_night["score"]["stage_summary"]
        print(f"\n📉 WORST NIGHT — {format_date(w_night['start'])} ({int(w_score)}% performance)")
        print(f"   {millis_to_hours(w_stages['total_in_bed_time_milli'])}h in bed  |  "
              f"{millis_to_hours(w_stages['total_rem_sleep_time_milli'])}h REM  |  "
              f"{millis_to_hours(w_stages['total_slow_wave_sleep_time_milli'])}h deep")

    print("\n" + "=" * 60)


# ── Entry Point ────────────────────────────────────────────────────────────────

def main():
    print("=== Sleep Analysis ===")

    client = WhoopClient()

    # Fetch last 25 nights (max per page — enough for ~1 month)
    print("Fetching sleep data...")
    response = client.get_sleep_collection(limit=25)
    records = response.get("records", [])

    print(f"Got {len(records)} records from Whoop.")
    analyze_sleep(records)


if __name__ == "__main__":
    main()
