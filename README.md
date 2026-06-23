# Health Dashboard

A Python project that pulls personal health data from **Whoop** and **Garmin Connect** APIs, combines them, and surfaces insights about recovery, sleep, and training load.

## What It Does

- Authenticates with the Whoop API (OAuth 2.0) and Garmin Connect API
- Fetches daily recovery scores, sleep data, HRV, strain, and activity metrics
- Stores data locally for analysis
- (Planned) Cross-references Whoop recovery with Garmin training load

## Why I Built This

I wanted a hands-on project to learn how to work with real-world REST APIs, manage authentication (including OAuth), and structure Python code cleanly. Health data felt like a natural fit since I use both devices daily and care about the data they produce.

## Tech Stack

- **Python 3.11+**
- **Requests** — HTTP calls to the Whoop API
- **python-garminconnect** — community wrapper for the Garmin Connect API
- **python-dotenv** — keeps API credentials out of the code
- **pandas** (planned) — data analysis and combination

## Project Structure

```
health-dashboard/
├── README.md               # You're reading it
├── requirements.txt        # All Python dependencies
├── .env.example            # Template for credentials (safe to share)
├── .gitignore              # Keeps secrets and junk out of GitHub
├── src/
│   ├── whoop_client.py     # All Whoop API logic lives here
│   ├── garmin_client.py    # All Garmin API logic lives here (coming soon)
│   └── main.py             # Entry point — runs everything
└── data/                   # Local data storage (gitignored)
```

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/YOUR_USERNAME/health-dashboard.git
cd health-dashboard
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Set up your credentials

```bash
cp .env.example .env
# Then open .env and fill in your Whoop client ID and secret
```

To get Whoop credentials:
1. Go to [developer-dashboard.whoop.com](https://developer-dashboard.whoop.com)
2. Create a new app
3. Copy your Client ID and Client Secret into `.env`

### 3. Run it

```bash
python src/main.py
```

## Key Concepts Learned

- **OAuth 2.0** — the industry-standard auth protocol used by Whoop. Your app never sees the user's password; instead it gets a temporary access token.
- **REST APIs** — making HTTP requests (GET, POST) to structured endpoints that return JSON data
- **Environment variables** — how to keep secrets out of your code and out of GitHub
- **Python project structure** — separating concerns into modules so code stays organized as it grows

## Status

- [x] Project structure and setup
- [x] Whoop OAuth authentication
- [x] Whoop data fetching (recovery, sleep, workouts)
- [ ] Garmin Connect integration
- [ ] Combined analysis

---

*Built as a portfolio project to learn API integration and Python project structure.*
