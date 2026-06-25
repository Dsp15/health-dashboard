"""
whoop_client.py

Handles all communication with the Whoop API.

The Whoop API uses OAuth 2.0 — an industry-standard authorization protocol.
Here's the basic flow:
  1. We redirect the user to Whoop's login page
  2. After they log in, Whoop sends us a temporary "code"
  3. We exchange that code for an "access token"
  4. We use that access token on every API request to prove who we are

Docs: https://developer.whoop.com/docs/developing/oauth
API reference: https://developer.whoop.com/api
"""

import os
import json
import secrets
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs
import requests
from dotenv import load_dotenv

load_dotenv()

# ── Constants ──────────────────────────────────────────────────────────────────

WHOOP_AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
WHOOP_API_BASE = "https://api.prod.whoop.com/developer/v2"

# Scopes tell Whoop what data our app is allowed to read.
# We're requesting the minimum we need — good security practice.
SCOPES = "read:recovery read:cycles read:sleep read:workout read:profile read:body_measurement offline"

# Where to store the token so we don't re-authenticate every time
TOKEN_FILE = ".whoop_token.json"


# ── OAuth Flow ─────────────────────────────────────────────────────────────────

class _CallbackHandler(BaseHTTPRequestHandler):
    """
    Tiny local web server that catches the OAuth redirect.
    When Whoop redirects to http://localhost:8080/callback?code=...,
    this handler captures the code and stores it.
    """
    code = None
    expected_state = None

    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        if "code" in params and params.get("state", [None])[0] == _CallbackHandler.expected_state:
            _CallbackHandler.code = params["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h2>Authenticated! You can close this tab.</h2>")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"<h2>Error: no code received.</h2>")

    def log_message(self, format, *args):
        # Suppress the default request logging so our terminal stays clean
        pass


def _get_new_token(client_id: str, client_secret: str, redirect_uri: str) -> dict:
    """
    Runs the full OAuth browser flow and returns a token dict.
    Only needed on first run or when the refresh token expires.
    """
    # Step 1: Build the URL that sends the user to Whoop's login page
    # The state parameter is a random string we generate and verify on return —
    # it prevents CSRF attacks (someone tricking our server into accepting a fake callback)
    state = secrets.token_urlsafe(16)
    _CallbackHandler.expected_state = state

    auth_params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
    }
    auth_url = f"{WHOOP_AUTH_URL}?{urlencode(auth_params)}"

    print("\n Opening your browser to log in to Whoop...")
    print(" If it doesn't open, go to this URL manually:")
    print(f"  {auth_url}\n")
    webbrowser.open(auth_url)

    # Step 2: Start a local server to catch the redirect from Whoop
    server = HTTPServer(("localhost", 8080), _CallbackHandler)
    print(" Waiting for Whoop to redirect back...")
    server.handle_request()  # Blocks until one request comes in

    code = _CallbackHandler.code
    if not code:
        raise RuntimeError("OAuth failed — no code received from Whoop.")

    # Step 3: Exchange the code for an access token
    response = requests.post(WHOOP_TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    })
    response.raise_for_status()

    print(" Authentication successful!\n")
    return response.json()


def _refresh_token(client_id: str, client_secret: str, refresh_token: str) -> dict:
    """
    Use the refresh token to get a new access token without re-logging in.
    Access tokens expire after a short time; refresh tokens last much longer.
    """
    response = requests.post(WHOOP_TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    response.raise_for_status()
    return response.json()


def _load_token() -> dict | None:
    """Load a previously saved token from disk, if it exists."""
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return json.load(f)
    return None


def _save_token(token: dict):
    """Save token to disk so we don't need to re-authenticate next time."""
    with open(TOKEN_FILE, "w") as f:
        json.dump(token, f, indent=2)


# ── Main Client Class ──────────────────────────────────────────────────────────

class WhoopClient:
    """
    A simple client for the Whoop API.

    Usage:
        client = WhoopClient()
        recovery = client.get_recovery_collection(limit=7)
    """

    def __init__(self):
        self.client_id = os.getenv("WHOOP_CLIENT_ID")
        self.client_secret = os.getenv("WHOOP_CLIENT_SECRET")
        self.redirect_uri = os.getenv("WHOOP_REDIRECT_URI", "http://localhost:8080/callback")

        if not self.client_id or not self.client_secret:
            raise ValueError(
                "Missing WHOOP_CLIENT_ID or WHOOP_CLIENT_SECRET in your .env file.\n"
                "Get these from https://developer-dashboard.whoop.com"
            )

        self.token = self._authenticate()

    def _authenticate(self) -> dict:
        """
        Load a saved token if available, otherwise run the browser flow.
        This means you only have to log in once.
        """
        token = _load_token()

        if token and token.get("refresh_token"):
            print("Found saved Whoop token, refreshing...")
            try:
                token = _refresh_token(self.client_id, self.client_secret, token["refresh_token"])
                _save_token(token)
                return token
            except requests.HTTPError:
                print("Refresh failed — need to log in again.")

        # No saved token or refresh failed — run the full browser flow
        token = _get_new_token(self.client_id, self.client_secret, self.redirect_uri)
        _save_token(token)
        return token

    def _headers(self) -> dict:
        """Build the Authorization header required for every API request."""
        return {"Authorization": f"Bearer {self.token['access_token']}"}

    def _get(self, endpoint: str, params: dict = None) -> dict:
        """
        Make a GET request to the Whoop API.
        Centralizing this here means if we ever need to handle errors
        or retries, we only change it in one place.
        """
        url = f"{WHOOP_API_BASE}{endpoint}"
        response = requests.get(url, headers=self._headers(), params=params)
        response.raise_for_status()
        return response.json()

    def _get_all(self, endpoint: str, start: str = None, end: str = None) -> list:
        """
        Fetch ALL records from a paginated endpoint by following next_token pages.

        The Whoop API returns max 25 records per page. If there are more, it
        includes a 'next_token' in the response. We keep requesting the next page
        until there are no more records. This is called pagination.

        Think of it like a book — instead of getting all pages at once,
        we get one chapter at a time until we reach the end.
        """
        records = []
        params = {"limit": 25}
        if start:
            params["start"] = start
        if end:
            params["end"] = end

        while True:
            response = self._get(endpoint, params=params)
            records.extend(response.get("records", []))

            next_token = response.get("next_token")
            if not next_token:
                break  # No more pages — we're done

            params["nextToken"] = next_token  # Ask for the next page

        return records

    # ── Data Methods ───────────────────────────────────────────────────────────

    def get_profile(self) -> dict:
        """Get basic user profile info."""
        return self._get("/user/profile/basic")

    def get_body_measurements(self) -> dict:
        """Get height, weight, and max heart rate."""
        return self._get("/user/measurement/body")

    def get_recovery_collection(self, limit: int = 25, start: str = None, end: str = None) -> dict:
        """Get a page of recovery records. Use get_all_recovery() to fetch everything."""
        params = {"limit": limit}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        return self._get("/recovery", params=params)

    def get_sleep_collection(self, limit: int = 25, start: str = None, end: str = None) -> dict:
        """Get a page of sleep records. Use get_all_sleep() to fetch everything."""
        params = {"limit": limit}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        return self._get("/activity/sleep", params=params)

    def get_workout_collection(self, limit: int = 25, start: str = None, end: str = None) -> dict:
        """Get a page of workout records. Use get_all_workouts() to fetch everything."""
        params = {"limit": limit}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        return self._get("/activity/workout", params=params)

    def get_cycle_collection(self, limit: int = 25, start: str = None, end: str = None) -> dict:
        """Get a page of cycle records. Use get_all_cycles() to fetch everything."""
        params = {"limit": limit}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        return self._get("/cycle", params=params)

    # ── Paginated "get all" methods ────────────────────────────────────────────

    def get_all_sleep(self, start: str = None, end: str = None) -> list:
        """Fetch all sleep records across all pages for a date range."""
        return self._get_all("/activity/sleep", start=start, end=end)

    def get_all_recovery(self, start: str = None, end: str = None) -> list:
        """Fetch all recovery records across all pages for a date range."""
        return self._get_all("/recovery", start=start, end=end)

    def get_all_cycles(self, start: str = None, end: str = None) -> list:
        """Fetch all cycle records across all pages for a date range."""
        return self._get_all("/cycle", start=start, end=end)

    def get_all_workouts(self, start: str = None, end: str = None) -> list:
        """Fetch all workout records across all pages for a date range."""
        return self._get_all("/activity/workout", start=start, end=end)
