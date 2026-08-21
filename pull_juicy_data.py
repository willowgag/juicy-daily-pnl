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
    {"name": "Solea", "env_var": "JUICY_TOKEN_SOLEA"},
    {"name": "FloreVitale", "env_var": "JUICY_TOKEN_FLOREVITALE"},
]

JUICY_BASE_URL = "https://juicy.easyapps.cloud/api/stats/shop"

# Metrics we pull out of Juicy's response and write as sheet columns.
# Note: grossMarginV2, netMarginV2, and breakEvenRoasV2 are ratios/percentages -
# summing them across brands would be meaningless, so they're recalculated
# from the summed dollar totals in the Blended tab instead (see RATIO_METRICS below).
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
    "facebookImpressions",
    "facebookReach",
    "facebookFrequency",
    "facebookClicks",
    "facebookCtr",
    "facebookCpc",
    "facebookCpm",
    "facebookRoas",
    "facebookOrdersFloat",
    "facebookCpoFloat",
]

# Metrics that should NOT be summed across brands in the Blended tab -
# they're recalculated from other (summed) values instead.
RATIO_METRICS = {"grossMarginV2", "netMarginV2", "breakEvenRoasV2", "facebookCtr", "facebookCpc", "facebookCpm", "facebookRoas", "facebookCpoFloat", "facebookFrequency"}

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
    """Appends the row unless a row for that date already exists (avoids duplicate runs).
    Note: for writing many rows in a loop, prefer append_rows_if_new (batched) instead -
    calling this repeatedly does one read per call and can hit Google's rate limit."""
    existing_dates = worksheet.col_values(1)  # column A = Date
    if row[0] in existing_dates:
        print(f"  Row for {row[0]} already exists in '{worksheet.title}', skipping.")
        return
    worksheet.append_row(row)
    print(f"  Wrote row for {row[0]} to '{worksheet.title}'.")


def append_rows_if_new(worksheet, rows):
    """Batched version: reads existing dates ONCE, then writes all new rows in a single
    API call. Use this instead of calling append_row_if_new in a loop - looping the
    single-row version does one read per row and can exceed Google's per-minute quota."""
    if not rows:
        return
    existing_dates = set(worksheet.col_values(1))  # one read call for the whole batch
    new_rows = [row for row in rows if row[0] not in existing_dates]
    skipped = len(rows) - len(new_rows)

    if new_rows:
        worksheet.append_rows(new_rows)  # one write call for the whole batch
        for row in new_rows:
            print(f"  Wrote row for {row[0]} to '{worksheet.title}'.")
    if skipped:
        print(f"  Skipped {skipped} row(s) already present in '{worksheet.title}'.")


def sum_metric(value, total):
    """Adds value to total, treating blanks/None as 0. Keeps total as None if nothing summed yet."""
    if value in (None, ""):
        return total
    if total is None:
        return value
    return total + value


def compute_blended_totals(brand_rows):
    """Computes blended totals dict (metric_key -> value) from a list of brand rows for
    the same date. Shared by write_blended_row (writes to Sheet) and the Telegram
    notification (just needs the netProfitV2 figure), so the math lives in one place."""
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

    # Facebook rate metrics recalculated from underlying totals rather than averaged,
    # for accuracy (e.g. CTR = total clicks / total impressions, not avg of per-brand CTRs)
    fb_impressions = totals.get("facebookImpressions") or 0
    fb_clicks = totals.get("facebookClicks") or 0
    fb_spend = totals.get("facebookAdSpend") or 0
    fb_orders = totals.get("facebookOrdersFloat") or 0

    totals["facebookCtr"] = round((fb_clicks / fb_impressions) * 100, 2) if fb_impressions else ""
    totals["facebookCpc"] = round(fb_spend / fb_clicks, 2) if fb_clicks else ""
    totals["facebookCpm"] = round((fb_spend / fb_impressions) * 1000, 2) if fb_impressions else ""
    totals["facebookCpoFloat"] = round(fb_spend / fb_orders, 2) if fb_orders else ""
    # ROAS and Frequency don't have a clean underlying-totals recomputation available
    # here (ROAS needs attributed revenue, Frequency needs reach); average across
    # brands that reported a value as a reasonable approximation for Blended.
    fb_roas_values = [row[METRICS.index("facebookRoas") + 1] for row in brand_rows if row[METRICS.index("facebookRoas") + 1] not in (None, "")]
    totals["facebookRoas"] = round(sum(fb_roas_values) / len(fb_roas_values), 2) if fb_roas_values else ""
    fb_freq_values = [row[METRICS.index("facebookFrequency") + 1] for row in brand_rows if row[METRICS.index("facebookFrequency") + 1] not in (None, "")]
    totals["facebookFrequency"] = round(sum(fb_freq_values) / len(fb_freq_values), 2) if fb_freq_values else ""

    return totals


def write_blended_row(sheet, date_str, brand_rows):
    """Computes a blended row for this date and writes it into the 'Blended' tab
    (creating it if needed). Dollar-value metrics are summed across brands; ratio/
    percentage metrics (margins, break-even ROAS) are recalculated from the summed
    dollar totals rather than naively summed, since summing percentages is meaningless."""
    title = "Blended"
    try:
        ws = sheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=title, rows=1000, cols=len(SHEET_HEADER) + 1)
        ws.append_row(SHEET_HEADER)

    totals = compute_blended_totals(brand_rows)

    blended_row = [date_str] + [
        totals[metric_key] if totals[metric_key] not in (None,) else ""
        for metric_key in METRICS
    ]
    append_row_if_new(ws, blended_row)
    return ws


def export_json_for_dashboard(sheet, brand_names, output_path="docs/data.json"):
    """Reads every row from each brand tab + Blended tab and writes it all into a single
    JSON file the GitHub Pages dashboard can fetch. Structure:
    { "Nordik": [{date, netProfitV2, ...}, ...], "Lymphea": [...], "Blended": [...] }

    Merges into the existing file rather than overwriting it, since a separate
    workflow (pull_payouts_data.py) writes its own "Payouts" key into the same
    file - overwriting here would silently erase that data whenever this script
    runs after the Payouts pull.
    """
    tabs_to_export = brand_names + ["Blended"]
    output = {}

    for tab_name in tabs_to_export:
        try:
            ws = sheet.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            print(f"  Tab '{tab_name}' not found, skipping in JSON export.")
            continue

        all_values = ws.get_all_values()
        if not all_values or len(all_values) < 2:
            output[tab_name] = []
            continue

        header = all_values[0]
        rows = all_values[1:]

        tab_records = []
        for row in rows:
            record = {}
            for i, col_name in enumerate(header):
                if not col_name:
                    continue  # skip blank/stray header columns rather than writing a "" key
                value = row[i] if i < len(row) else ""
                # try to convert numeric strings back to numbers for the dashboard
                if col_name != "Date" and value != "":
                    try:
                        value = float(value)
                    except ValueError:
                        pass
                record[col_name] = value
            tab_records.append(record)

        output[tab_name] = tab_records

    # Merge into existing data.json rather than overwrite - a separate script
    # (pull_payouts_data.py) writes its own "Payouts" key into this same file,
    # so we only replace our own keys (brand names + "Blended") and leave anything
    # else already in the file untouched.
    existing = {}
    if os.path.exists(output_path):
        try:
            with open(output_path, "r") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = {}

    existing.update(output)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(existing, f, indent=2)
    print(f"  Wrote dashboard data to {output_path}")

def send_telegram_message(text):
    """Sends a message via Telegram bot. Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
    env vars. Silently skips (with a log line) if either is missing, so this never
    breaks the main data pipeline if notifications aren't configured."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("  Telegram not configured (missing token or chat ID), skipping notification.")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}

    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        print("  Telegram notification sent.")
    except requests.exceptions.RequestException as e:
        print(f"  ERROR sending Telegram notification: {e}")


def get_month_to_date_profit(sheet, date_str):
    """Sums netProfitV2 from the Blended tab for every date in the same month as date_str,
    up to and including that date. Used for the 'month so far' notification figure."""
    month_prefix = date_str[:7]  # "YYYY-MM"

    try:
        ws = sheet.worksheet("Blended")
    except gspread.WorksheetNotFound:
        return None

    all_values = ws.get_all_values()
    if not all_values or len(all_values) < 2:
        return None

    header = all_values[0]
    rows = all_values[1:]

    try:
        date_col = header.index("Date")
        profit_col = header.index("netProfitV2")
    except ValueError:
        return None

    total = 0.0
    for row in rows:
        if len(row) <= max(date_col, profit_col):
            continue
        row_date = row[date_col]
        if row_date.startswith(month_prefix) and row_date <= date_str:
            try:
                total += float(row[profit_col])
            except (ValueError, IndexError):
                continue

    return total


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

    brand_rows = []

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
        brand_rows.append(row)

    if brand_rows:
        write_blended_row(sheet, date_from, brand_rows)
    else:
        print("  No brand data fetched, skipping Blended row.")

    print("Exporting dashboard JSON...")
    export_json_for_dashboard(sheet, [b["name"] for b in BRANDS])

    print("Sending Telegram notification...")
    if brand_rows:
        yesterday_profit = compute_blended_totals(brand_rows).get("netProfitV2", 0)
    else:
        yesterday_profit = 0
    month_to_date = get_month_to_date_profit(sheet, date_from)

    month_label = datetime.date.fromisoformat(date_from).strftime("%B")

    def fmt(n):
        sign = "-" if n < 0 else ""
        return f"{sign}${abs(n):,.2f}"

    message_lines = [
        f"Yesterday: {fmt(yesterday_profit)}",
    ]
    if month_to_date is not None:
        message_lines.append(f"{month_label}: {fmt(month_to_date)}")

    send_telegram_message("\n".join(message_lines))

    print("Done.")


if __name__ == "__main__":
    main()
