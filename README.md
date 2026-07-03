# Athlete Health Dashboard

A personal health analytics platform that pulls data from **Whoop** and **Garmin** fitness trackers, stores it in a PostgreSQL database, and displays it in a live web dashboard — so I can make smarter training decisions as a triathlete.

Built to solve a real problem: Whoop and Garmin each have their own apps, but neither shows you how the *two devices compare*, or how last night's sleep actually connects to today's recovery score. This dashboard puts it all in one place.

---

## What It Does

**Daily Health page**
- Stat cards showing today's recovery score, HRV, resting heart rate, sleep hours, and sleep score — with Garmin and Whoop side by side for comparison
- Click any point on any chart to inspect that day's stats (cards update instantly without a page reload)
- Weekly summary card that reads your numbers and generates a plain-English coaching insight
- 9 interactive charts: recovery trend, HRV trend, resting HR, sleep breakdown by stage, sleep performance, bedtime pattern, HRV vs recovery scatter plot, and dual-tracker comparison charts
- Date range toggle: 30 / 60 / 90 / 180 / 365 days / All Time
- Trend arrows comparing last 7 days to the previous 7 days

**Training page**
- Weekly training load by volume and sport
- Sport breakdown donut (swim / bike / run / strength)
- Training → next-day recovery: shows how each workout affected the following morning's Whoop score
- Half Ironman recovery story: dual-axis chart tracking recovery + HRV before and after the June 14, 2026 race

**Live sync**
- "Sync Now" button triggers a fresh data pull via WebSocket
- The browser updates without a page reload — charts refresh in place

---

## Why I Built This

I'm a triathlete and completed my first Half Ironman in June 2026. I wear a Whoop for recovery tracking and a Garmin for GPS and training load — but I can't wear either device during work hours, and neither app gives me a clean picture of how training and sleep interact over time.

I wanted to answer specific questions my devices couldn't:
- When my Whoop says recovery is low, does my Garmin resting HR agree?
- Is there a pattern between bedtime and next-day HRV?
- How long did it actually take to recover from the Half Ironman?
- Am I building fitness or accumulating fatigue?

Building this also gave me hands-on experience with the full stack of a real software product — from API integrations and database design to a web UI and real-time data sync.

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| **Database** | PostgreSQL 18 | Industry-standard relational database; handles date queries, aggregations, and multi-table joins cleanly |
| **ETL Pipeline** | Python | Pulls from two APIs, transforms data into a consistent schema, loads into PostgreSQL |
| **Web Server** | Flask (Python) | Lightweight Python web framework — same language as the pipeline |
| **Real-time sync** | Flask-SocketIO (WebSocket) | Lets the server push updates to the browser when sync completes — no page refresh needed |
| **Charts** | Chart.js 4.4 | Fast, interactive JavaScript charting — all charts rendered client-side |
| **Auth** | Whoop OAuth 2.0 | Industry-standard authorization flow — same pattern used by Spotify, Google, Strava |

---

## Architecture

```
Whoop API  ──┐
             ├──► Python ETL pipeline ──► PostgreSQL ──► Flask REST API ──► Browser
Garmin API ──┘                                                │
                                                              └──► WebSocket (live sync)
```

**Data flow:**
1. The pipeline authenticates with Whoop via OAuth 2.0 and Garmin Connect via session login
2. It pulls recovery, sleep, HRV, activities, and daily stats — back to May 2025 (Whoop) and April 2026 (Garmin)
3. Data is upserted into 8 PostgreSQL tables using `ON CONFLICT DO UPDATE` — running the pipeline twice never creates duplicates
4. Flask serves 10+ REST API endpoints that query PostgreSQL and return JSON
5. The browser fetches JSON and renders charts using Chart.js
6. Clicking "Sync Now" sends a WebSocket message; the server pulls fresh data and pushes `sync_complete` back to the browser, which reloads the charts

---

## Key Technical Decisions

**Why PostgreSQL instead of a spreadsheet?**
Two data sources with different schemas need joins. A single SQL query can say "show me every training session alongside next-morning recovery" — a spreadsheet can't do that reliably.

**Why upsert instead of insert?**
Whoop delivers recovery scores hours after you wake up, so data changes retroactively. `INSERT ... ON CONFLICT DO UPDATE` means re-running the pipeline always reflects the latest data, never creates duplicates.

**Why WebSockets instead of a page refresh?**
A normal refresh loses your selected date range and scroll position. A WebSocket keeps the connection open so the server can say "sync is done" and the browser reloads only the chart data — the UI state stays intact.

**Why two devices?**
Whoop focuses on recovery and sleep. Garmin focuses on GPS, training load, and HRV trends. The dual-tracker charts show where they agree (builds confidence in the data) and where they diverge (which is its own insight).

---

## Setup

```bash
# 1. Clone and install dependencies
git clone https://github.com/piersond16/health-dashboard.git
cd health-dashboard
pip install -r requirements.txt

# 2. Configure credentials
cp .env.example .env
# Edit .env with your Whoop API credentials and Garmin login

# 3. Run the full historical backfill
python src/pipeline.py --full

# 4. Start the dashboard
python src/app.py
# Open http://localhost:8080
```

---

## Project Stats

- ~4,000 lines of Python and JavaScript
- 8 PostgreSQL tables
- 2 API integrations (Whoop OAuth 2.0, Garmin Connect)
- 10+ REST API endpoints
- 9+ interactive charts with click-to-inspect and date range filtering

---

## What I Learned

**OAuth 2.0 in practice** — implementing the full authorization code flow: redirect the user, handle the callback, exchange a code for a token, refresh when it expires. Most production APIs use this pattern.

**ETL pipeline design** — how to pull from two APIs with different schemas, normalize them into a consistent database structure, and handle real-world data quality issues (missing values, late-arriving data, null fields when a device wasn't worn).

**SQL for analytics** — writing aggregations, date window comparisons, and multi-table joins to answer real questions. For example: comparing last 7 days vs previous 7 days to generate trend arrows, or joining activities to next-day recovery scores.

**WebSockets vs HTTP** — the difference between request/response HTTP (browser asks, server answers, connection closes) and WebSocket (connection stays open, server can push events). Knowing when each pattern makes sense is a common interview topic.

**Debugging without a manual** — PostgreSQL 18 silently removed support for `ROUND(double precision, integer)`. None of the chart data loaded. I diagnosed it from the error message, understood why it broke in this version, and fixed it across every affected query with a `::numeric` cast. Real bugs rarely come with instructions.

**Data quality at the source** — Garmin returns `null` for sleep when the device wasn't worn. Whoop's API sometimes omits days where data is still processing. Production data is always messier than the API docs suggest — the pipeline handles it gracefully with `or 0` defaults and `try/except` around each day's fetch.
