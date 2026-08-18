"""
Pulls current Shopify Payments balance and next scheduled payout for each
configured brand via Shopify's Admin GraphQL API, writes a daily snapshot
into a 'Payouts Raw' Google Sheet tab, computes a Blended row, and exports
everything into docs/data.json under a "Payouts" key.

Environment variables expected (set as GitHub Actions secrets):
  GOOGLE_SERVICE_ACCOUNT_JSON     - full contents of the service account JSON key
  GOOGLE_SHEET_ID                 - the ID from the sheet URL
  SHOPIFY_TOKEN_<BRANDNAME>       - one per brand, e.g. SHOPIFY_TOKEN_LYMPHEA
  SHOPIFY_DOMAIN_<BRANDNAME>      - the brand's *.myshopify.com domain

Brands are configured in the BRANDS list below. To add a new brand:
  1. Create a Shopify custom app for that store with scopes:
     read_shopify_payments_payouts, read_shopify_payments_accounts
  2. Add its token as SHOPIFY_TOKEN_<BRANDNAME> and domain as
     SHOPIFY_DOMAIN_<BRANDNAME> (both GitHub secrets)
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
    {"name": "Lymphea", "token_env": "SHOPIFY_TOKEN_LYMPHEA", "domain_env": "SHOPIFY_DOMAIN_LYMPHEA"},
    {"name": "Solea", "token_env": "SHOPIFY_TOKEN_SOLEA", "domain_env": "SHOPIFY_DOMAIN_SOLEA"},
    {"name": "FloreVitale", "token_env": "SHOPIFY_TOKEN_FLOREVITALE", "domain_env": "SHOPIFY_DOMAIN_FLOREVITALE"},
    {"name": "Nordik", "token_env": "SHOPIFY_TOKEN_NORDIK", "domain_env": "SHOPIFY_DOMAIN_NORDIK"},
]

RAW_TAB_NAME = "Payouts Raw"
RAW_HEADER = ["Date", "Brand", "Balance", "NextPayoutDate", "NextPayoutAmount", "Currency"]

GRAPHQL_QUERY = """
{
  shopifyPaymentsAccount {
    balance { amount currencyCode }
    payouts(first: 5, sortKey: ISSUED_AT, reverse: true) {
      edges {
        node { id issuedAt status net { amount currencyCode } }
      }
    }
  }
}
"""


# ---- Helpers ----

def get_today():
    return datetime.date.today().isoformat()


def fetch_payouts_data(domain, token):
    """Calls Shopify's Admin GraphQL API for balance + recent/scheduled payouts."""
    url = f"https://{domain}/admin/api/2026-07/graphql.json"
    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": token,
    }
    response = requests.post(url, headers=headers, json={"query": GRAPHQL_QUERY}, timeout=30)
    response.raise_for_status()
    data = response.json()
    if "errors" in data:
        raise RuntimeError(f"Shopify GraphQL error: {data['errors']}")
    return data["data"]["shopifyPaymentsAccount"]


def extract_snapshot(account_data):
    """Pulls balance and the next SCHEDULED payout (if any) out of the account data.
    Returns (balance_amount, currency, next_payout_date, next_payout_amount)."""
    balance_list = account_data.get("balance", [])
    balance_amount = float(balance_list[0]["amount"]) if balance_list else 0.0
    currency = balance_list[0]["currencyCode"] if balance_list else ""

    next_payout_date = ""
    next_payout_amount = ""

    payout_edges = account_data.get("payouts", {}).get("edges", [])
    # payouts are sorted newest-first; find the first SCHEDULED one
    for edge in payout_edges:
        node = edge["node"]
        if node.get("status") == "SCHEDULED":
            next_payout_date = node["issuedAt"][:10]  # trim to YYYY-MM-DD
            next_payout_amount = float(node["net"]["amount"])
            break

    return balance_amount, currency, next_payout_date, next_payout_amount


def get_or_create_worksheet(sheet, title, header):
    try:
        ws = sheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=title, rows=1000, cols=len(header) + 1)
        ws.append_row(header)
    return ws


def append_rows_if_new(worksheet, rows):
    """Reads existing (Date, Brand) pairs once, appends only genuinely new rows,
    in a single batched write."""
    if not rows:
        return
    all_values = worksheet.get_all_values()
    existing = {(row[0], row[1]) for row in all_values[1:] if len(row) >= 2}
    new_rows = [row for row in rows if (row[0], row[1]) not in existing]
    if new_rows:
        worksheet.append_rows(new_rows)
        for row in new_rows:
            print(f"  Wrote payout snapshot for {row[1]} on {row[0]}.")
    skipped = len(rows) - len(new_rows)
    if skipped:
        print(f"  Skipped {skipped} row(s) already present.")


def export_payouts_json(sheet, brand_names, output_path="docs/data.json"):
    """Reads 'Payouts Raw', computes latest snapshot per brand + Blended,
    merges into docs/data.json under the "Payouts" key without overwriting
    other keys already written by pull_juicy_data.py / export_mrr_data.py."""
    try:
        ws = sheet.worksheet(RAW_TAB_NAME)
    except gspread.WorksheetNotFound:
        print(f"  Tab '{RAW_TAB_NAME}' not found, skipping Payouts export.")
        return

    all_values = ws.get_all_values()
    if not all_values or len(all_values) < 2:
        print("  No payout rows yet, skipping Payouts export.")
        return

    header = all_values[0]
    rows = all_values[1:]

    records = []
    for row in rows:
        record = {}
        for i, col_name in enumerate(header):
            value = row[i] if i < len(row) else ""
            if col_name in ("Balance", "NextPayoutAmount") and value != "":
                try:
                    value = float(value)
                except ValueError:
                    pass
            record[col_name] = value
        records.append(record)

    # Latest snapshot per brand (by most recent Date) - used for the summary tiles
    latest_by_brand = {}
    for r in records:
        name = r["Brand"]
        if name not in latest_by_brand or r["Date"] > latest_by_brand[name]["Date"]:
            latest_by_brand[name] = r

    # Full history per brand, sorted oldest to newest - used for the history table
    history_by_brand = {}
    for r in records:
        name = r["Brand"]
        history_by_brand.setdefault(name, []).append(r)
    for name in history_by_brand:
        history_by_brand[name].sort(key=lambda r: r["Date"])

    payouts_output = {}
    for name in brand_names:
        if name in latest_by_brand:
            payouts_output[name] = dict(latest_by_brand[name])
            payouts_output[name]["History"] = history_by_brand.get(name, [])

    # Blended: sum balances and next-payout amounts across brands with a snapshot today
    total_balance = sum((r.get("Balance") or 0) for r in latest_by_brand.values())
    total_next_payout = sum((r.get("NextPayoutAmount") or 0) for r in latest_by_brand.values() if r.get("NextPayoutAmount"))
    # Use the soonest next payout date among brands that have one, for display purposes
    next_dates = [r["NextPayoutDate"] for r in latest_by_brand.values() if r.get("NextPayoutDate")]
    soonest_date = min(next_dates) if next_dates else ""
    currency = next(iter(latest_by_brand.values()), {}).get("Currency", "")

    # Blended history: sum Balance/NextPayoutAmount across brands for each date that
    # has at least one brand's snapshot that day
    all_dates = sorted(set(r["Date"] for r in records))
    blended_history = []
    for date_str in all_dates:
        day_records = [r for r in records if r["Date"] == date_str]
        day_balance = sum((r.get("Balance") or 0) for r in day_records)
        day_next_amounts = [r.get("NextPayoutAmount") or 0 for r in day_records if r.get("NextPayoutAmount")]
        day_next_dates = [r["NextPayoutDate"] for r in day_records if r.get("NextPayoutDate")]
        blended_history.append({
            "Date": date_str,
            "Brand": "Blended",
            "Balance": round(day_balance, 2),
            "NextPayoutDate": min(day_next_dates) if day_next_dates else "",
            "NextPayoutAmount": round(sum(day_next_amounts), 2) if day_next_amounts else "",
            "Currency": day_records[0].get("Currency", "") if day_records else "",
        })

    payouts_output["Blended"] = {
        "Date": max((r["Date"] for r in latest_by_brand.values()), default=""),
        "Brand": "Blended",
        "Balance": round(total_balance, 2),
        "NextPayoutDate": soonest_date,
        "NextPayoutAmount": round(total_next_payout, 2),
        "Currency": currency,
        "History": blended_history,
    }

    existing = {}
    if os.path.exists(output_path):
        try:
            with open(output_path, "r") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = {}

    existing["Payouts"] = payouts_output

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(existing, f, indent=2)
    print(f"  Wrote Payouts data to {output_path}")


# ---- Main ----

def main():
    google_creds_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    sheet_id = os.environ["GOOGLE_SHEET_ID"]

    creds_dict = json.loads(google_creds_json)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(sheet_id)

    today = get_today()
    print(f"Pulling payouts data for {today}...")

    rows_to_write = []

    for brand in BRANDS:
        name = brand["name"]
        token = os.environ.get(brand["token_env"])
        domain = os.environ.get(brand["domain_env"])

        if not token or not domain:
            print(f"  Skipping {name}: missing token or domain env var.")
            continue

        print(f"  Fetching {name}...")
        try:
            account_data = fetch_payouts_data(domain, token)
        except (requests.exceptions.RequestException, RuntimeError) as e:
            print(f"  ERROR fetching {name}: {e}")
            continue

        balance, currency, next_date, next_amount = extract_snapshot(account_data)
        rows_to_write.append([today, name, balance, next_date, next_amount, currency])

    ws = get_or_create_worksheet(sheet, RAW_TAB_NAME, RAW_HEADER)
    append_rows_if_new(ws, rows_to_write)

    print("Exporting Payouts dashboard JSON...")
    export_payouts_json(sheet, [b["name"] for b in BRANDS])

    print("Done.")


if __name__ == "__main__":
    main()
