# Juicy Daily P&L Pull

Automated daily pull of P&L data (revenue, COGS, ad spend, profit) from Juicy's API
for each connected brand, written into its own tab in a Google Sheet.

Runs daily via GitHub Actions. Free to run — no LLM involved, just a scheduled script.

## One-time setup

### 1. Google Sheet

1. Create a blank Google Sheet.
2. Copy its ID from the URL: `docs.google.com/spreadsheets/d/THIS_PART/edit`

### 2. Google Service Account

1. In [Google Cloud Console](https://console.cloud.google.com), create a project.
2. Enable the **Google Sheets API**.
3. Create a **Service Account**, then create a JSON key for it.
4. Share your Google Sheet with the service account's email (found in the JSON key),
   giving it **Editor** access.

### 3. Juicy API tokens

1. In Juicy, switch to each store using the store dropdown.
2. Go to **AI & API access**, create a token for that store.
3. Repeat for each brand.

### 4. GitHub repo secrets

In this repo, go to **Settings → Secrets and variables → Actions**, add:

| Secret name | Value |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full contents of the service account JSON key file |
| `GOOGLE_SHEET_ID` | The sheet ID from step 1 |
| `JUICY_TOKEN_NORDIK` | Nordik's Juicy API token |
| `JUICY_TOKEN_LYMPHEA` | Lymphea's Juicy API token |

### 5. Test it

Go to the **Actions** tab in this repo, select **Daily Juicy P&L Pull**, click
**Run workflow** to trigger it manually and confirm it writes data correctly
before waiting for the schedule.

## Adding a new brand later

1. Create a Juicy API token for the new store (switch to it in Juicy's dropdown first).
2. Add a new GitHub secret, e.g. `JUICY_TOKEN_ROMEO`.
3. In `pull_juicy_data.py`, add one line to the `BRANDS` list:
   ```python
   {"name": "Romeo", "env_var": "JUICY_TOKEN_ROMEO"},
   ```
4. In `.github/workflows/daily-pull.yml`, add the corresponding env line under
   the `Run daily pull` step:
   ```yaml
   JUICY_TOKEN_ROMEO: ${{ secrets.JUICY_TOKEN_ROMEO }}
   ```
5. Commit and push. The script will auto-create a new sheet tab for the brand
   on its next run.

## What it does each day

1. Runs at 9:00 AM UTC (adjust the cron schedule in the workflow file for your timezone).
2. For each configured brand, calls Juicy's `/api/stats/shop` endpoint for yesterday's date.
3. Extracts key metrics (revenue, COGS, ad spend, profit, margins, orders, break-even ROAS).
4. Writes one row per brand into that brand's own sheet tab.
5. Skips writing if a row for that date already exists (safe to re-run manually).
