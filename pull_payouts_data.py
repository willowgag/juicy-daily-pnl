"""
Pulls Shopify Payments balance and the payout ledger (individual payout records,
matching Shopify's own Payouts page: date, status, amount) for each configured
brand via Shopify's Admin GraphQL API. Writes one row per payout into a
'Payouts Raw' Google Sheet tab (deduplicated by Shopify's payout ID, so re-runs
never create duplicates even as new payouts appear over time), plus a small
'Balance Raw' tab tracking the current balance per brand per day. Exports
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

PAYOUTS_TAB_NAME = "Payouts Raw"
PAYOUTS_HEADER = ["PayoutId", "Brand", "Date", "Status", "Amount", "Currency"]

BALANCE_TAB_NAME = "Balance Raw"
BALANCE_HEADER = ["Date", "Brand", "Balance", "Currency"]

# Pull a wide window of payouts each run so the ledger builds up a real history
# quickly even though we only run once a day - each is deduplicated by PayoutId.
GRAPHQL_QUERY = """
{
  shopifyPaymentsAccount {
    balance { amount currencyCode }
    payouts(first: 30, sortKey: ISSUED_AT, reverse: true) {
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


def extract_balance(account_data):
    balance_list = account_data.get("balance", [])
    balance_amount = float(balance_list[0]["amount"]) if balance_list else 0.0
    currency = balance_list[0]["currencyCode"] if balance_list else ""
    return balance_amount, currency


def extract_payout_rows(account_data, brand_name):
    """Returns one row per payout: [PayoutId, Brand, Date, Status, Amount, Currency]."""
    rows = []
    payout_edges = account_data.get("payouts", {}).get("edges", [])
    for edge in payout_edges:
        node = edge["node"]
        payout_id = node["id"]
        date_str = node["issuedAt"][:10]
        status = node.get("status", "")
        amount = float(node["net"]["amount"])
        currency = node["net"]["currencyCode"]
        rows.append([payout_id, brand_name, date_str, status, amount, currency])
    return rows


def get_or_create_worksheet(sheet, title, header):
    try:
        ws = sheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=title, rows=2000, cols=len(header) + 1)
        ws.append_row(header)
    return ws


def append_payout_rows_if_new(worksheet, rows):
    """Dedupes by PayoutId (column A)."""
    if not rows:
        return
    all_values = worksheet.get_all_values()
    existing_ids = {row[0] for row in all_values[1:] if row}
    new_rows = [row for row in rows if row[0] not in existing_ids]
    if new_rows:
        worksheet.append_rows(new_rows)
        print(f"  Wrote {len(new_rows)} new payout row(s).")
    skipped = len(rows) - len(new_rows)
    if skipped:
        print(f"  Skipped {skipped} payout(s) already recorded.")


def update_payout_statuses(worksheet, rows):
    """Updates the Status cell for any existing payout rows whose status has
    changed since last recorded (e.g. SCHEDULED -> PAID). One batched read,
    only writes cells that actually changed."""
    all_values = worksheet.get_all_values()
    if len(all_values) < 2:
        return

    header = all_values[0]
    id_col = header.index("PayoutId")
    status_col = header.index("Status")

    id_to_row_num = {row[id_col]: i + 2 for i, row in enumerate(all_values[1:]) if row}

    updates = []
    for row in rows:
        payout_id, _, _, new_status, _, _ = row
        row_num = id_to_row_num.get(payout_id)
        if row_num is None:
            continue
        existing_row = all_values[row_num - 1]
        current_status = existing_row[status_col] if status_col < len(existing_row) else ""
        if current_status != new_status:
            cell_label = gspread.utils.rowcol_to_a1(row_num, status_col + 1)
            updates.append({"range": cell_label, "values": [[new_status]]})

    if updates:
        worksheet.batch_update(updates)
        print(f"  Updated status on {len(updates)} existing payout(s).")


def append_balance_rows_if_new(worksheet, rows):
    if not rows:
        return
    all_values = worksheet.get_all_values()
    existing = {(row[0], row[1]) for row in all_values[1:] if len(row) >= 2}
    new_rows = [row for row in rows if (row[0], row[1]) not in existing]
    if new_rows:
        worksheet.append_rows(new_rows)
        print(f"  Wrote {len(new_rows)} balance snapshot(s).")
    skipped = len(rows) - len(new_rows)
    if skipped:
        print(f"  Skipped {skipped} balance snapshot(s) already present.")


def export_payouts_json(sheet, brand_names, output_path="docs/data.json"):
    """Reads the full payout ledger + latest balance per brand, merges into
    docs/data.json under the "Payouts" key without overwriting other keys."""
    try:
        payouts_ws = sheet.worksheet(PAYOUTS_TAB_NAME)
        payout_values = payouts_ws.get_all_values()
    except gspread.WorksheetNotFound:
        payout_values = []

    try:
        balance_ws = sheet.worksheet(BALANCE_TAB_NAME)
        balance_values = balance_ws.get_all_values()
    except gspread.WorksheetNotFound:
        balance_values = []

    if not payout_values or len(payout_values) < 2:
        print("  No payout rows yet, skipping Payouts export.")
        return

    payout_header = payout_values[0]
    payout_records = []
    for row in payout_values[1:]:
        record = {}
        for i, col_name in enumerate(payout_header):
            value = row[i] if i < len(row) else ""
            if col_name == "Amount" and value != "":
                try:
                    value = float(value)
                except ValueError:
                    pass
            record[col_name] = value
        payout_records.append(record)

    balance_records = []
    if balance_values and len(balance_values) >= 2:
        balance_header = balance_values[0]
        for row in balance_values[1:]:
            record = {}
            for i, col_name in enumerate(balance_header):
                value = row[i] if i < len(row) else ""
                if col_name == "Balance" and value != "":
                    try:
                        value = float(value)
                    except ValueError:
                        pass
                record[col_name] = value
            balance_records.append(record)

    payouts_by_brand = {}
    for r in payout_records:
        payouts_by_brand.setdefault(r["Brand"], []).append(r)
    for name in payouts_by_brand:
        payouts_by_brand[name].sort(key=lambda r: r["Date"], reverse=True)

    latest_balance_by_brand = {}
    for r in balance_records:
        name = r["Brand"]
        if name not in latest_balance_by_brand or r["Date"] > latest_balance_by_brand[name]["Date"]:
            latest_balance_by_brand[name] = r

    payouts_output = {}
    for name in brand_names:
        brand_payouts = payouts_by_brand.get(name, [])
        next_scheduled = next((p for p in brand_payouts if p["Status"] == "SCHEDULED"), None)
        payouts_output[name] = {
            "Balance": (latest_balance_by_brand.get(name) or {}).get("Balance", 0),
            "Currency": (latest_balance_by_brand.get(name) or {}).get("Currency", ""),
            "NextPayoutDate": next_scheduled["Date"] if next_scheduled else "",
            "NextPayoutAmount": next_scheduled["Amount"] if next_scheduled else "",
            "Payouts": brand_payouts,
        }

    total_balance = sum((v["Balance"] or 0) for v in payouts_output.values())
    next_amounts = [v["NextPayoutAmount"] for v in payouts_output.values() if v["NextPayoutAmount"]]
    next_dates = [v["NextPayoutDate"] for v in payouts_output.values() if v["NextPayoutDate"]]
    currency = next((v["Currency"] for v in payouts_output.values() if v["Currency"]), "")

    all_payouts_sorted = sorted(payout_records, key=lambda r: r["Date"], reverse=True)

    payouts_output["Blended"] = {
        "Balance": round(total_balance, 2),
        "Currency": currency,
        "NextPayoutDate": min(next_dates) if next_dates else "",
        "NextPayoutAmount": round(sum(next_amounts), 2) if next_amounts else "",
        "Payouts": all_payouts_sorted,
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

    all_payout_rows = []
    all_balance_rows = []

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

        balance, currency = extract_balance(account_data)
        all_balance_rows.append([today, name, balance, currency])

        payout_rows = extract_payout_rows(account_data, name)
        all_payout_rows.extend(payout_rows)

    payouts_ws = get_or_create_worksheet(sheet, PAYOUTS_TAB_NAME, PAYOUTS_HEADER)
    append_payout_rows_if_new(payouts_ws, all_payout_rows)
    update_payout_statuses(payouts_ws, all_payout_rows)

    balance_ws = get_or_create_worksheet(sheet, BALANCE_TAB_NAME, BALANCE_HEADER)
    append_balance_rows_if_new(balance_ws, all_balance_rows)

    print("Exporting Payouts dashboard JSON...")
    export_payouts_json(sheet, [b["name"] for b in BRANDS])

    print("Done.")


if __name__ == "__main__":
    main()
