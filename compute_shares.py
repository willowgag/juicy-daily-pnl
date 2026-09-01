"""
Computes profit-share amounts owed to a partner per brand, reads payments already
made (logged via the dashboard's text box -> Apps Script webhook -> Google Sheet),
and exports everything into docs/data.json under a "Shares" key for the dashboard.

Share percentages are configured in SHARE_CONFIG below. To add a brand, add one
line - the brand name must match exactly how it appears in the P&L tabs.

Losses subtract from what's owed: the share is calculated on cumulative net profit
across all time, so a losing day genuinely reduces the partner's balance rather
than being ignored.

Environment variables expected (same GOOGLE_* secrets as the other scripts):
  GOOGLE_SERVICE_ACCOUNT_JSON
  GOOGLE_SHEET_ID
"""

import os
import json
import gspread
from google.oauth2.service_account import Credentials

# ---- Config ----

# brand name -> partner's share of that brand's net profit (0.70 = 70%)
SHARE_CONFIG = {
    "Nordik": 0.70,
    "Aera": 0.50,
}

PAYMENTS_TAB_NAME = "Shares Payments"
PAYMENTS_HEADER = ["Date", "Recipient", "Amount", "Note"]

OUTPUT_PATH = "docs/data.json"


def read_tab_records(sheet, tab_name):
    """Reads a tab into a list of dicts, converting numeric-looking values to floats."""
    try:
        ws = sheet.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        return []

    all_values = ws.get_all_values()
    if not all_values or len(all_values) < 2:
        return []

    header = all_values[0]
    records = []
    for row in all_values[1:]:
        record = {}
        for i, col_name in enumerate(header):
            if not col_name:
                continue
            value = row[i] if i < len(row) else ""
            if col_name not in ("Date", "Recipient", "Note", "Brand") and value != "":
                try:
                    value = float(value)
                except ValueError:
                    pass
            record[col_name] = value
        records.append(record)
    return records


def compute_shares(sheet):
    """For each configured brand, sums its all-time net profit and applies the
    partner's share percentage. Returns per-brand detail plus overall totals."""
    per_brand = {}
    total_owed = 0.0

    for brand_name, share_pct in SHARE_CONFIG.items():
        rows = read_tab_records(sheet, brand_name)
        net_profit = sum((r.get("netProfitV2") or 0) for r in rows if isinstance(r.get("netProfitV2"), (int, float)))
        owed = net_profit * share_pct
        total_owed += owed

        per_brand[brand_name] = {
            "SharePct": round(share_pct * 100, 1),
            "NetProfit": round(net_profit, 2),
            "Owed": round(owed, 2),
            "DaysCounted": len(rows),
        }

    return per_brand, round(total_owed, 2)


def get_or_create_payments_tab(sheet):
    try:
        return sheet.worksheet(PAYMENTS_TAB_NAME)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=PAYMENTS_TAB_NAME, rows=1000, cols=len(PAYMENTS_HEADER) + 1)
        ws.append_row(PAYMENTS_HEADER)
        print(f"  Created '{PAYMENTS_TAB_NAME}' tab.")
        return ws


def export_shares_json(sheet, output_path=OUTPUT_PATH):
    """Computes shares + payments and merges into docs/data.json under "Shares",
    leaving other keys (P&L brands, Payouts) untouched."""
    get_or_create_payments_tab(sheet)  # ensure it exists even before first payment

    per_brand, total_owed = compute_shares(sheet)

    payments = read_tab_records(sheet, PAYMENTS_TAB_NAME)
    payments_sorted = sorted(payments, key=lambda p: p.get("Date", ""), reverse=True)
    total_paid = sum((p.get("Amount") or 0) for p in payments if isinstance(p.get("Amount"), (int, float)))

    shares_output = {
        "PerBrand": per_brand,
        "TotalOwed": total_owed,
        "TotalPaid": round(total_paid, 2),
        "Balance": round(total_owed - total_paid, 2),
        "Payments": payments_sorted,
    }

    existing = {}
    if os.path.exists(output_path):
        try:
            with open(output_path, "r") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = {}

    existing["Shares"] = shares_output

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(existing, f, indent=2)

    print(f"  Total owed: ${total_owed:,.2f} | Paid: ${total_paid:,.2f} | Balance: ${total_owed - total_paid:,.2f}")
    print(f"  Wrote Shares data to {output_path}")


def main():
    google_creds_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    sheet_id = os.environ["GOOGLE_SHEET_ID"]

    creds_dict = json.loads(google_creds_json)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(sheet_id)

    print("Computing profit shares...")
    export_shares_json(sheet)
    print("Done.")


if __name__ == "__main__":
    main()
