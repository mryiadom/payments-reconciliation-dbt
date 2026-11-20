"""Download the ECB's daily euro reference rates and keep the ones this project needs.

The ECB publishes one file holding every rate since 1999. This script downloads it,
keeps four currencies for the project's date range, and writes a small CSV file that is
committed to the repo, so nobody needs the internet to run the project.

Source: https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html
Run from the repo root:  python generator/download_ecb_rates.py
"""

import csv
import io
import urllib.request
import zipfile
from pathlib import Path

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
CURRENCIES = ["GBP", "USD", "SEK", "JPY"]  # EUR is the base, so it has no row
START_DATE = "2026-06-01"
END_DATE = "2026-11-30"
OUTPUT_FILE = Path(__file__).parent / "reference" / "ecb_rates.csv"


def download_ecb_csv_text():
    """Download the ECB zip file and return the text of the CSV inside it."""
    with urllib.request.urlopen(ECB_URL) as response:
        zip_bytes = response.read()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zip_file:
        return zip_file.read("eurofxref-hist.csv").decode("utf-8")


def pick_rates(csv_text, start_date, end_date, currencies):
    """Turn the ECB's wide table (one column per currency) into one row per currency per day.

    Dates are written as YYYY-MM-DD, so comparing them as plain text puts them in
    the right order. A rate of "N/A" means the ECB did not publish one, so it is skipped.
    """
    rows = []
    for ecb_row in csv.DictReader(io.StringIO(csv_text)):
        rate_date = ecb_row["Date"]
        if not start_date <= rate_date <= end_date:
            continue
        for currency in currencies:
            rate = ecb_row[currency]
            if rate == "N/A":
                continue
            # The rate is kept as text, exactly as the ECB wrote it, so nothing is rounded.
            rows.append({"rate_date": rate_date, "currency": currency, "rate_per_eur": rate})
    return sorted(rows, key=lambda row: (row["rate_date"], row["currency"]))


def write_rates(rows, output_file):
    """Write the rows to a CSV file, creating the folder if needed."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["rate_date", "currency", "rate_per_eur"])
        writer.writeheader()
        writer.writerows(rows)


def main():
    csv_text = download_ecb_csv_text()
    rows = pick_rates(csv_text, START_DATE, END_DATE, CURRENCIES)
    write_rates(rows, OUTPUT_FILE)
    print(f"Wrote {len(rows)} rows to {OUTPUT_FILE}")
    print(f"Dates covered: {rows[0]['rate_date']} to {rows[-1]['rate_date']}")


if __name__ == "__main__":
    main()
