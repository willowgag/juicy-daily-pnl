"""
ONE-TIME backfill script. Pulls historical P&L data from Juicy for each brand,
starting from that brand's own start date, up through yesterday, and writes it
into the same Google Sheet the daily script uses. Then recomputes the Blended
tab for every date and regenerates docs/data.json.

Run this manually once (not on a schedule):
    python backfill_juicy_data.py

Uses the same env vars as pull_juicy_data.py:
  GOOGLE_SERVICE_ACCOUNT_JSON
  GOOGLE_SHEET_ID
  JUICY_TOKEN_NORDIK
  JUICY_TOKEN_LYMPHEA

Edit BACKFILL_START_DATES below before running to set each brand's start date.
"""

import os
import json
import datetime
import gspread
from google.oauth2.service_account import Credentials

from pull_juicy_data import (
    BRANDS,
    METRICS,
    SHEET_HEADER,
    fetch_juicy_stats,
    get_or_create_worksheet,
    append_row_if_new,
    write_blended_row,
    export_json_for_dashboard,
)

# ---- Backfill config: edit these before running ----

BACKFILL_START_DATES = {
    "Nordik": "2026-07-01",
    "Lymphea": "2026-07-25",
}


def get_yesterday():
    return (datetime.date.today() - datetime.timedelta(days=1)).isoformat()


def daterange(start_date_str, end_date_str):
    """Yields each date string from start to end, inclusive."""
    start = datetime.date.fromisoformat(start_date_str)
    end = datetime.date.fromisoformat(end_date_str)
    current = start
    while current <= end:
        yield current.isoformat()
        current += datetime.timedelta(days=1)


def extract_all_rows(data, date_from, date_to):
    """Pulls every day's values out of Juicy's dataV2 structure for the whole range,
    returning a dict of {date: row}."""
    metrics = data.get("dataV2", {})
    rows_by_date = {}

    for date_str in daterange(date_from, date_to):
        row = [date_str]
        for metric_key in METRICS:
            metric = metrics.get(metric_key)
            value = None
            if metric and metric.get("current") and metric["current"].get("data"):
                for point in metric["current"]["data"]:
                    if point.get("date") == date_str:
                        value = point.get("value")
                        break
            row.append(value if value is not None else "")
        rows_by_date[date_str] = row

    return rows_by_date


def main():
    google_creds_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    sheet_id = os.environ["GOOGLE_SHEET_ID"]

    creds_dict = json.loads(google_creds_json)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(sheet_id)

    yesterday = get_yesterday()

    # Fetch each brand's full range in one call, keyed by date for easy lookup
    brand_rows_by_date = {}  # { "Nordik": {date: row, ...}, "Lymphea": {...} }

    for brand in BRANDS:
        name = brand["name"]
        start_date = BACKFILL_START_DATES.get(name)
        if not start_date:
            print(f"No start date configured for {name}, skipping.")
            continue

        token = os.environ.get(brand["env_var"])
        if not token:
            print(f"No token found for {name} ({brand['env_var']}), skipping.")
            continue

        print(f"Fetching {name} from {start_date} to {yesterday}...")
        data = fetch_juicy_stats(token, start_date, yesterday)
        rows_by_date = extract_all_rows(data, start_date, yesterday)
        brand_rows_by_date[name] = rows_by_date

        ws = get_or_create_worksheet(sheet, name)
        for date_str, row in rows_by_date.items():
            append_row_if_new(ws, row)

        print(f"  Backfilled {len(rows_by_date)} days for {name}.")

    # Recompute Blended for every date that has at least one brand's data
    print("Rebuilding Blended tab...")
    all_dates = set()
    for rows_by_date in brand_rows_by_date.values():
        all_dates.update(rows_by_date.keys())

    for date_str in sorted(all_dates):
        rows_for_this_date = [
            brand_rows_by_date[name][date_str]
            for name in brand_rows_by_date
            if date_str in brand_rows_by_date[name]
        ]
        if rows_for_this_date:
            write_blended_row(sheet, date_str, rows_for_this_date)

    print("Exporting dashboard JSON...")
    export_json_for_dashboard(sheet, [b["name"] for b in BRANDS])

    print("Backfill complete.")


if __name__ == "__main__":
    main()
