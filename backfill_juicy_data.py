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
    RATIO_METRICS,
    SHEET_HEADER,
    fetch_juicy_stats,
    get_or_create_worksheet,
    append_rows_if_new,
    sum_metric,
    export_json_for_dashboard,
)

# ---- Backfill config: edit these before running ----

BACKFILL_START_DATES = {
    "Nordik": "2026-07-01",
    "Lymphea": "2026-07-25",
    "Solea": "2026-07-01",
    "FloreVitale": "2026-08-12",
    "Aera": "2026-08-19",
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


def compute_blended_row(date_str, brand_rows):
    """Same math as write_blended_row in pull_juicy_data.py, but returns the row
    instead of writing it immediately - lets the caller batch all rows into one write."""
    totals = {metric_key: None for metric_key in METRICS}

    for row in brand_rows:
        for i, metric_key in enumerate(METRICS):
            if metric_key in RATIO_METRICS:
                continue
            totals[metric_key] = sum_metric(row[i + 1], totals[metric_key])

    net_revenue = totals.get("netRevenueV2") or 0
    gross_profit = totals.get("grossProfitV2") or 0
    net_profit = totals.get("netProfitV2") or 0
    cogs = totals.get("cogsV2") or 0
    transaction_fees = totals.get("transactionFees") or 0

    totals["grossMarginV2"] = round((gross_profit / net_revenue) * 100, 2) if net_revenue else ""
    totals["netMarginV2"] = round((net_profit / net_revenue) * 100, 2) if net_revenue else ""
    break_even_denominator = net_revenue - cogs - transaction_fees
    totals["breakEvenRoasV2"] = round(net_revenue / break_even_denominator, 2) if break_even_denominator else ""

    fb_impressions = totals.get("facebookImpressions") or 0
    fb_clicks = totals.get("facebookClicks") or 0
    fb_spend = totals.get("facebookAdSpend") or 0
    fb_orders = totals.get("facebookOrdersFloat") or 0

    totals["facebookCtr"] = round((fb_clicks / fb_impressions) * 100, 2) if fb_impressions else ""
    totals["facebookCpc"] = round(fb_spend / fb_clicks, 2) if fb_clicks else ""
    totals["facebookCpm"] = round((fb_spend / fb_impressions) * 1000, 2) if fb_impressions else ""
    totals["facebookCpoFloat"] = round(fb_spend / fb_orders, 2) if fb_orders else ""
    fb_roas_values = [row[METRICS.index("facebookRoas") + 1] for row in brand_rows if row[METRICS.index("facebookRoas") + 1] not in (None, "")]
    totals["facebookRoas"] = round(sum(fb_roas_values) / len(fb_roas_values), 2) if fb_roas_values else ""
    fb_freq_values = [row[METRICS.index("facebookFrequency") + 1] for row in brand_rows if row[METRICS.index("facebookFrequency") + 1] not in (None, "")]
    totals["facebookFrequency"] = round(sum(fb_freq_values) / len(fb_freq_values), 2) if fb_freq_values else ""

    return [date_str] + [
        totals[metric_key] if totals[metric_key] not in (None,) else ""
        for metric_key in METRICS
    ]


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
        all_rows = list(rows_by_date.values())
        append_rows_if_new(ws, all_rows)

        print(f"  Backfilled {len(rows_by_date)} days for {name}.")

    # Recompute Blended for every date that has at least one brand's data
    print("Rebuilding Blended tab...")
    all_dates = set()
    for rows_by_date in brand_rows_by_date.values():
        all_dates.update(rows_by_date.keys())

    blended_rows = []
    for date_str in sorted(all_dates):
        rows_for_this_date = [
            brand_rows_by_date[name][date_str]
            for name in brand_rows_by_date
            if date_str in brand_rows_by_date[name]
        ]
        if rows_for_this_date:
            blended_rows.append(compute_blended_row(date_str, rows_for_this_date))

    blended_ws = get_or_create_worksheet(sheet, "Blended")
    # Clear existing rows and rewrite fresh - Blended is fully derived from brand tabs,
    # so it's always safe to regenerate rather than append-and-skip. This matters when
    # a new brand is added: old Blended rows (computed without that brand) need to be
    # replaced, not left in place, or the new brand never gets counted historically.
    existing_row_count = len(blended_ws.get_all_values())
    if existing_row_count > 1:
        blended_ws.batch_clear([f"A2:Z{existing_row_count}"])
        print(f"  Cleared {existing_row_count - 1} existing Blended row(s) for a clean rebuild.")
    if blended_rows:
        blended_ws.append_rows(blended_rows)
        print(f"  Wrote {len(blended_rows)} Blended row(s).")

    print("Exporting dashboard JSON...")
    export_json_for_dashboard(sheet, [b["name"] for b in BRANDS])

    print("Backfill complete.")


if __name__ == "__main__":
    main()
