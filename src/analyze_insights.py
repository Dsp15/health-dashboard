"""
analyze_insights.py

Comprehensive analysis pulling together sleep, recovery, cycles, and workouts
to surface the most actionable insights from your Whoop data.

Insights covered:
  - HRV trend and what's driving it up/down
  - Sleep debt accumulation
  - Strain vs next-day recovery
  - Your personal recovery fingerprint
  - Day-by-day timeline

Run it:
    python src/analyze_insights.py
"""

from whoop_client import WhoopClient
from datetime import datetime, timezone


# ── Helpers ────────────────────────────────────────────────────────────────────

def millis_to_hours(ms: int) -> float:
    return round(ms / 3_600_000, 1)

def format_date(iso_string: str) -> str:
    dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
    return dt.strftime("%b %d")

def month_key(iso_string: str) -> str:
    """Returns a sortable year-month string like '2025-06'."""
    dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
    return dt.strftime("%Y-%m")

def day_of_week(iso_string: str) -> str:
    dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
    return dt.strftime("%a")

def recovery_bar(score: float) -> str:
    """Visual bar that shows recovery as green/yellow/red."""
    if score is None:
        return "n/a"
    bar = "█" * int(score / 10)
    if score >= 67:
        return f"🟢 {bar}"
    elif score >= 34:
        return f"🟡 {bar}"
    else:
        return f"🔴 {bar}"

def hrv_trend(hrv_list: list) -> str:
    """Returns ↑ ↓ → based on recent HRV direction."""
    if len(hrv_list) < 3:
        return "→"
    recent = sum(hrv_list[:3]) / 3
    older  = sum(hrv_list[3:6]) / max(len(hrv_list[3:6]), 1)
    if recent > older * 1.05:
        return "↑ improving"
    elif recent < older * 0.95:
        return "↓ declining"
    else:
        return "→ stable"


# ── Data Joining ───────────────────────────────────────────────────────────────

def build_daily_records(sleep_records, recovery_records, cycle_records, workout_records):
    """
    Join all four data streams on cycle_id to create one unified record per day.
    This is the core data engineering step — turning four separate API responses
    into one clean dataset we can analyze.
    """
    # Build lookup dicts by cycle_id
    recovery_by_cycle = {
        r["cycle_id"]: r for r in recovery_records
        if r.get("score_state") == "SCORED"
    }
    sleep_by_cycle = {
        r["cycle_id"]: r for r in sleep_records
        if r.get("score_state") == "SCORED" and not r.get("nap")
    }
    cycle_by_id = {c["id"]: c for c in cycle_records}

    # Group workouts by cycle_id (there can be multiple workouts per day)
    workouts_by_cycle: dict = {}
    for w in workout_records:
        if w.get("score_state") == "SCORED":
            cid = w.get("cycle_id")
            if cid:
                workouts_by_cycle.setdefault(cid, []).append(w)

    # Build unified daily records
    daily = []
    for cycle_id, recovery in recovery_by_cycle.items():
        sleep   = sleep_by_cycle.get(cycle_id)
        cycle   = cycle_by_id.get(cycle_id)
        workouts = workouts_by_cycle.get(cycle_id, [])

        if not sleep or not cycle:
            continue

        sleep_score  = sleep.get("score", {})
        stages       = sleep_score.get("stage_summary", {})
        rec_score    = recovery.get("score", {})
        cycle_score  = cycle.get("score", {})

        # Total workout strain for the day
        total_strain = sum(w["score"].get("strain", 0) for w in workouts if w.get("score"))
        sport_names  = [w.get("sport_name", "unknown") for w in workouts]

        daily.append({
            "date":               format_date(sleep["start"]),
            "month_key":          month_key(sleep["start"]),
            "sort_key":           sleep["start"],  # ISO string — sorts chronologically
            "day":                day_of_week(sleep["start"]),
            "sleep_hours":        millis_to_hours(stages.get("total_in_bed_time_milli", 0)),
            "sleep_needed_hours": millis_to_hours(
                sleep_score.get("sleep_needed", {}).get("baseline_milli", 0) +
                sleep_score.get("sleep_needed", {}).get("need_from_sleep_debt_milli", 0) +
                sleep_score.get("sleep_needed", {}).get("need_from_recent_strain_milli", 0)
            ),
            "sleep_debt_hours":   millis_to_hours(
                sleep_score.get("sleep_needed", {}).get("need_from_sleep_debt_milli", 0)
            ),
            "rem_hours":          millis_to_hours(stages.get("total_rem_sleep_time_milli", 0)),
            "deep_hours":         millis_to_hours(stages.get("total_slow_wave_sleep_time_milli", 0)),
            "sleep_performance":  sleep_score.get("sleep_performance_percentage"),
            "recovery_score":     rec_score.get("recovery_score"),
            "hrv":                rec_score.get("hrv_rmssd_milli"),
            "resting_hr":         rec_score.get("resting_heart_rate"),
            "day_strain":         cycle_score.get("strain"),
            "workout_strain":     total_strain if total_strain > 0 else None,
            "sports":             ", ".join(sport_names) if sport_names else None,
        })

    # Sort oldest to newest using the ISO date string (sorts correctly as text)
    return sorted(daily, key=lambda x: x["sort_key"])


# ── Analysis ───────────────────────────────────────────────────────────────────

def analyze(daily: list) -> None:
    if not daily:
        print("Not enough data to analyze.")
        return

    n = len(daily)
    print(f"\nAnalyzing {n} days of combined Whoop data\n")

    # ── Full Timeline ─────────────────────────────────────────────
    print("=" * 75)
    print("\n📅 FULL TIMELINE")
    print(f"\n{'Date':<8} {'Day':<4} {'Sleep':>5} {'Perf':>5} {'Rec':>4} {'HRV':>5} {'RHR':>4} {'Strain':>7} {'Sport':<15}")
    print("-" * 75)

    for d in daily:
        rec = d["recovery_score"]
        emoji = "🟢" if rec and rec >= 67 else ("🟡" if rec and rec >= 34 else "🔴")
        print(
            f"{d['date']:<8} "
            f"{d['day']:<4} "
            f"{d['sleep_hours']:>4}h "
            f"{int(d['sleep_performance'] or 0):>4}% "
            f"{emoji}{int(rec or 0):>3}% "
            f"{round(d['hrv'] or 0):>5} "
            f"{int(d['resting_hr'] or 0):>4} "
            f"{round(d['day_strain'] or 0, 1):>7} "
            f"{(d['sports'] or '')[:15]:<15}"
        )

    # ── Overall Averages ──────────────────────────────────────────
    def avg(key):
        vals = [d[key] for d in daily if d[key] is not None]
        return round(sum(vals) / len(vals), 1) if vals else 0

    print("\n" + "=" * 75)
    print("\n📊 YOUR AVERAGES")
    print(f"  Recovery score:      {avg('recovery_score')}%")
    print(f"  HRV (RMSSD):         {avg('hrv')} ms")
    print(f"  Resting heart rate:  {avg('resting_hr')} bpm")
    print(f"  Sleep performance:   {avg('sleep_performance')}%")
    print(f"  Sleep duration:      {avg('sleep_hours')}h")
    print(f"  Day strain:          {avg('day_strain')}")

    # ── HRV Trend ─────────────────────────────────────────────────
    hrv_list = [d["hrv"] for d in reversed(daily) if d["hrv"] is not None]
    trend = hrv_trend(hrv_list)
    print(f"\n📈 HRV TREND:  {trend}")
    print(f"   Last 3 days avg: {round(sum(hrv_list[:3])/3, 1) if len(hrv_list) >= 3 else 'n/a'} ms")
    print(f"   Overall avg:     {round(sum(hrv_list)/len(hrv_list), 1) if hrv_list else 'n/a'} ms")
    if hrv_list and hrv_list[0] > sum(hrv_list)/len(hrv_list):
        print("   ✅ Your HRV today is above your recent average — good sign.")
    elif hrv_list:
        print("   ⚠️  Your HRV today is below your recent average — body may be under stress.")

    # ── Sleep Debt ────────────────────────────────────────────────
    total_debt = sum(d["sleep_debt_hours"] for d in daily if d["sleep_debt_hours"])
    avg_debt   = total_debt / n
    print(f"\n😴 SLEEP DEBT")
    print(f"   Average sleep needed:  {avg('sleep_needed_hours')}h per night")
    print(f"   Average sleep gotten:  {avg('sleep_hours')}h per night")
    print(f"   Average sleep debt:    {round(avg_debt, 1)}h per night")
    gap = avg('sleep_needed_hours') - avg('sleep_hours')
    if gap > 0.5:
        print(f"   ⚠️  You're consistently under-sleeping by ~{round(gap, 1)}h.")
    else:
        print(f"   ✅ You're meeting your sleep need most nights.")

    # ── Strain vs Next-Day Recovery ───────────────────────────────
    print(f"\n💪 STRAIN vs NEXT-DAY RECOVERY")
    high_strain_days = [(daily[i], daily[i+1]) for i in range(len(daily)-1)
                        if daily[i]["day_strain"] and daily[i]["day_strain"] > 14]
    low_strain_days  = [(daily[i], daily[i+1]) for i in range(len(daily)-1)
                        if daily[i]["day_strain"] and daily[i]["day_strain"] <= 10]

    if high_strain_days:
        avg_rec_after_high = sum(b["recovery_score"] for _, b in high_strain_days
                                 if b["recovery_score"]) / len(high_strain_days)
        print(f"   After high strain days (>14):  avg next-day recovery = {round(avg_rec_after_high)}%")
    if low_strain_days:
        avg_rec_after_low = sum(b["recovery_score"] for _, b in low_strain_days
                                if b["recovery_score"]) / len(low_strain_days)
        print(f"   After low strain days (≤10):   avg next-day recovery = {round(avg_rec_after_low)}%")

    # ── Personal Recovery Fingerprint ────────────────────────────
    green_days = [d for d in daily if d["recovery_score"] and d["recovery_score"] >= 67]
    red_days   = [d for d in daily if d["recovery_score"] and d["recovery_score"] < 34]

    if green_days:
        print(f"\n🟢 YOUR GREEN DAY FINGERPRINT ({len(green_days)} green days)")
        g_hrv   = [d["hrv"] for d in green_days if d["hrv"]]
        g_sleep = [d["sleep_hours"] for d in green_days]
        g_rhr   = [d["resting_hr"] for d in green_days if d["resting_hr"]]
        print(f"   HRV:           {round(sum(g_hrv)/len(g_hrv), 1)} ms  (your avg: {avg('hrv')} ms)")
        print(f"   Sleep:         {round(sum(g_sleep)/len(g_sleep), 1)}h  (your avg: {avg('sleep_hours')}h)")
        print(f"   Resting HR:    {round(sum(g_rhr)/len(g_rhr), 1)} bpm  (your avg: {avg('resting_hr')} bpm)")

    if red_days:
        print(f"\n🔴 YOUR RED DAY FINGERPRINT ({len(red_days)} red days)")
        r_hrv   = [d["hrv"] for d in red_days if d["hrv"]]
        r_sleep = [d["sleep_hours"] for d in red_days]
        if r_hrv:
            print(f"   HRV:    {round(sum(r_hrv)/len(r_hrv), 1)} ms")
        print(f"   Sleep:  {round(sum(r_sleep)/len(r_sleep), 1)}h")

    # ── Month-by-Month Trends ─────────────────────────────────────
    print(f"\n📆 MONTH-BY-MONTH TRENDS")
    from collections import defaultdict
    from datetime import datetime

    # Use year-month as key so Jun 2025 and Jun 2026 are separate
    month_groups: dict = defaultdict(list)
    for d in daily:
        # d["date"] is "Jun 20" — we need the full date from the raw start
        # Re-parse using the index position in daily (already sorted by date)
        # Instead, store the sort key directly
        month_groups[d["month_key"]].append(d)

    # Sort chronologically
    sorted_months = sorted(month_groups.keys())

    print(f"\n  {'Month':<12} {'Days':>5} {'Rec%':>6} {'HRV':>7} {'Sleep':>6} {'RHR':>5}")
    print(f"  {'-'*12} {'-'*5} {'-'*6} {'-'*7} {'-'*6} {'-'*5}")

    for month_key in sorted_months:
        group  = month_groups[month_key]
        recs   = [d["recovery_score"] for d in group if d["recovery_score"]]
        hrvs   = [d["hrv"] for d in group if d["hrv"]]
        sleeps = [d["sleep_hours"] for d in group if d["sleep_hours"]]
        rhrs   = [d["resting_hr"] for d in group if d["resting_hr"]]
        if not recs:
            continue
        # Format key "2025-06" as "Jun 2025"
        label = datetime.strptime(month_key, "%Y-%m").strftime("%b %Y")
        print(
            f"  {label:<12} "
            f"{len(group):>5} "
            f"{round(sum(recs)/len(recs)):>5}% "
            f"{round(sum(hrvs)/len(hrvs), 1):>7} "
            f"{round(sum(sleeps)/len(sleeps), 1):>5}h "
            f"{round(sum(rhrs)/len(rhrs), 1):>5}"
        )

    print("\n" + "=" * 75)


# ── Entry Point ────────────────────────────────────────────────────────────────

def main():
    print("=== Comprehensive Whoop Insights ===")

    client = WhoopClient()

    START = "2025-05-01T00:00:00.000Z"  # ~1 year of data

    print("Fetching all data streams...")
    sleep_records    = client.get_all_sleep(start=START)
    recovery_records = client.get_all_recovery(start=START)
    cycle_records    = client.get_all_cycles(start=START)
    workout_records  = client.get_all_workouts(start=START)

    print(f"Got: {len(sleep_records)} sleep, {len(recovery_records)} recovery, "
          f"{len(cycle_records)} cycles, {len(workout_records)} workouts")

    daily = build_daily_records(sleep_records, recovery_records, cycle_records, workout_records)
    analyze(daily)


if __name__ == "__main__":
    main()
