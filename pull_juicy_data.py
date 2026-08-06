"""
Pulls daily P&L data from Juicy for each configured brand and writes it
into a dedicated tab per brand in a Google Sheet, plus updates a Blended tab.

Environment variables expected (set as GitHub Actions secrets):
  GOOGLE_SERVICE_ACCOUNT_JSON  - full contents of the service account JSON key
  GOOGLE_SHEET_ID              - the ID from the sheet URL
  JUICY_TOKEN_<BRANDNAME>      - one per brand, e.g. JUICY_TOKEN_NORDIK

Brands are configured in the BRANDS list below. To add a new brand:
  1. Create a Juicy API token for that store
  2. Add it as a GitHub secret named JUICY_TOKEN_<BRANDNAME> (uppercase, no spaces)
  3. Add one entry to the BRANDS list below
"""

import os
import json
import datetime
import requests
import gspread
from google.oauth2.service_account import Credentials

# ---- Config ----

BRANDS = [
    {"name": "Nordik", "env_var": "JUICY_TOKEN_NORDIK"},
    {"name": "Lymphea", "env_var": "JUICY_TOKEN_LYMPHEA"},
]

JUICY_BASE_URL = "https://juicy.easyapps.cloud/api/stats/shop"

# Metrics we pull out of Juicy's response and write as sheet columns
METRICS = [
    "grossSalesV2",
    "discountsV2",
    "totalSalesV2",
    "netRevenueV2",
    "cogsV2",
    "transactionFees",
    "grossProfitV2",
    "totalAdSpend",
    "facebookAdSpend",
    "googleAdSpend",
    "netProfitV2",
    "grossMarginV2",
    "netMarginV2",
    "ordersFloat",
    "breakEvenRoasV2",
]

SHEET_HEADER = ["Date"] + METRICS


# ---- Helpers ----

def get_yesterday_range():
    """Returns (dateFrom, dateTo) for yesterday, in YYYY-MM-DD format."""
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    date_str = yesterday.isoformat()
    return date_str, date_str


def fetch_juicy_stats(token, date_from, date_to):
    """Calls Juicy's shop stats endpoint and returns the parsed JSON."""
    url = f"{JUICY_BASE_URL}?dateFrom={date_from}&dateTo={date_to}"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def extract_row(data, date_str):
    """Pulls the single day's value for each metric out of Juicy's dataV2 structure."""
    row = [date_str]
    metrics = data.get("dataV2", {})
    for metric_key in METRICS:
        metric = metrics.get(metric_key)
        value = None
        if metric and metric.get("current") and metric["current"].get("data"):
            for point in metric["current"]["data"]:
                if point.get("date") == date_str:
                    value = point.get("value")
                    break
        row.append(value if value is not None else "")
    return row


def get_or_create_worksheet(sheet, title):
    """Returns the worksheet with this title, creating it with a header row if needed."""
    try:
        ws = sheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=title, rows=1000, cols=len(SHEET_HEADER) + 1)
        ws.append_row(SHEET_HEADER)
    return ws


def append_row_if_new(worksheet, row):
    """Appends the row unless a row for that date already exists (avoids duplicate runs)."""
    existing_dates = worksheet.col_values(1)  # column A = Date
    if row[0] in existing_dates:
        print(f"  Row for {row[0]} already exists in '{worksheet.title}', skipping.")
        return
    worksheet.append_row(row)
    print(f"  Wrote row for {row[0]} to '{worksheet.title}'.")


def ensure_blended_tab(sheet, brand_names):
    """Creates a 'Blended' tab with SUM formulas across all brand tabs, if it doesn't exist."""
    title = "Blended"
    try:
        ws = sheet.worksheet(title)
        return ws
    except gspread.WorksheetNotFound:
        pass

    ws = sheet.add_worksheet(title=title, rows=1000, cols=len(SHEET_HEADER) + 1)
    ws.append_row(SHEET_HEADER)
    print(f"  Created '{title}' tab. Add SUM/QUERY formulas manually or extend this script to populate it.")
    return ws


# ---- Main ----

def main():
    google_creds_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    sheet_id = os.environ["GOOGLE_SHEET_ID"]

    creds_dict = json.loads(google_creds_json)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(sheet_id)

    date_from, date_to = get_yesterday_range()
    print(f"Pulling Juicy data for {date_from}...")

    for brand in BRANDS:
        token = os.environ.get(brand["env_var"])
        if not token:
            print(f"  Skipping {brand['name']}: no token found in {brand['env_var']}")
            continue

        print(f"  Fetching {brand['name']}...")
        try:
            data = fetch_juicy_stats(token, date_from, date_to)
        except requests.exceptions.RequestException as e:
            print(f"  ERROR fetching {brand['name']}: {e}")
            continue

        row = extract_row(data, date_from)
        ws = get_or_create_worksheet(sheet, brand["name"])
        append_row_if_new(ws, row)

    ensure_blended_tab(sheet, [b["name"] for b in BRANDS])
    print("Done.")


if __name__ == "__main__":
    main()
