"""Generate clean payments and matching settlement files for Northgate Pay.

"Clean" means nothing has gone wrong yet: every payment is settled once, at the right
amount, on time. A later change plants problems on top of this clean data.

The same seed always gives the same files.
Run from the repo root:  python generator/generate_data.py --seed 42
"""

import argparse
import csv
import random
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SEEDS_DIR = REPO_ROOT / "payments_recon" / "seeds"
RATES_FILE = Path(__file__).parent / "reference" / "ecb_rates.csv"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data"

START_DATE = date(2026, 6, 1)
END_DATE = date(2026, 11, 30)
DEFAULT_SEED = 42
DEFAULT_PAYMENT_COUNT = 50_000

CURRENCIES = ["GBP", "EUR", "USD", "SEK", "JPY"]
# How many digits come after the decimal point. JPY has none, so it is whole yen.
DECIMAL_PLACES = {"GBP": 2, "EUR": 2, "USD": 2, "SEK": 2, "JPY": 0}
# Smallest and largest payment per currency, in minor units (pence, cents, ore, yen).
AMOUNT_RANGES = {
    "GBP": (500, 50_000),
    "EUR": (500, 50_000),
    "USD": (500, 50_000),
    "SEK": (5_000, 500_000),
    "JPY": (1_000, 80_000),
}
SHARE_IN_MERCHANT_CURRENCY = 0.8  # the rest are paid in one of the other currencies
FX_RATE_PLACES = Decimal("0.00000001")  # rates are kept to 8 decimal places


# ---------- Reading the input files ----------


def read_csv(path):
    """Read a CSV file into a list of dictionaries, one per row."""
    with open(path, newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def load_bank_holidays():
    """Return the UK bank holidays as a set of dates."""
    rows = read_csv(SEEDS_DIR / "bank_holidays.csv")
    return {date.fromisoformat(row["holiday_date"]) for row in rows}


def load_rates():
    """Return the ECB rates as {(date, currency): units of that currency per 1 EUR}."""
    rows = read_csv(RATES_FILE)
    return {(date.fromisoformat(r["rate_date"]), r["currency"]): Decimal(r["rate_per_eur"]) for r in rows}


# ---------- Money and dates ----------


def round_half_up(value):
    """Round a Decimal to a whole number, with .5 going up (the usual school rule)."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def is_business_day(day, holidays):
    """A business day is Monday to Friday and not a UK bank holiday."""
    return day.weekday() < 5 and day not in holidays


def add_business_days(start, days, holidays):
    """Move forward by a number of business days, skipping weekends and holidays."""
    current = start
    while days > 0:
        current += timedelta(days=1)
        if is_business_day(current, holidays):
            days -= 1
    return current


def rate_per_eur(rates, currency, on_date):
    """Units of a currency per 1 EUR on a date. If the ECB published nothing that day
    (weekend, holiday, or after the last published rate), use the most recent earlier rate."""
    if currency == "EUR":
        return Decimal(1)
    day = on_date
    for _ in range(60):
        if (day, currency) in rates:
            return rates[(day, currency)]
        day -= timedelta(days=1)
    raise ValueError(f"No {currency} rate found on or before {on_date}")


def fx_rate(rates, from_currency, to_currency, on_date):
    """How many units of to_currency one unit of from_currency buys, worked out through EUR."""
    rate = rate_per_eur(rates, to_currency, on_date) / rate_per_eur(rates, from_currency, on_date)
    return rate.quantize(FX_RATE_PLACES, rounding=ROUND_HALF_UP)


def convert_minor_units(amount, from_currency, to_currency, rate):
    """Convert an amount in minor units. Go to whole units, apply the rate, go back to minor units."""
    whole_units = Decimal(amount) / Decimal(10 ** DECIMAL_PLACES[from_currency])
    converted = whole_units * rate * Decimal(10 ** DECIMAL_PLACES[to_currency])
    return round_half_up(converted)


def pick_fee_plan(fee_plans, fee_tier, currency, on_date):
    """Find the one fee plan for this tier and currency that applies on this date."""
    day = on_date.isoformat()  # ISO dates sort correctly as plain text
    matches = [
        plan
        for plan in fee_plans
        if plan["fee_tier"] == fee_tier
        and plan["currency"] == currency
        and plan["valid_from"] <= day
        and (plan["valid_to"] == "" or day <= plan["valid_to"])
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one fee plan for {fee_tier} {currency} on {day}, found {len(matches)}")
    return matches[0]


# ---------- Making the data ----------


def make_payments(rng, merchants, count):
    """Make payments with random merchants, amounts and times, numbered in time order."""
    total_days = (END_DATE - START_DATE).days + 1
    raw_payments = []
    for _ in range(count):
        created_at = datetime.combine(START_DATE + timedelta(days=rng.randrange(total_days)), datetime.min.time())
        created_at += timedelta(seconds=rng.randrange(86_400))
        merchant = rng.choice(merchants)
        if rng.random() < SHARE_IN_MERCHANT_CURRENCY:
            currency = merchant["settlement_currency"]
        else:
            currency = rng.choice([c for c in CURRENCIES if c != merchant["settlement_currency"]])
        low, high = AMOUNT_RANGES[currency]
        raw_payments.append((created_at, merchant["merchant_id"], currency, rng.randint(low, high)))

    raw_payments.sort()  # earliest first, so payment numbers rise with time
    return [
        {
            "payment_id": f"PAY-{number:06d}",
            "merchant_id": merchant_id,
            "amount_minor_units": amount,
            "currency": currency,
            "created_at": created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "payment_type": "payment",
            "linked_payment_id": "",
        }
        for number, (created_at, merchant_id, currency, amount) in enumerate(raw_payments, start=1)
    ]


def make_settlement_line(rng, number, payment, merchant, fee_plans, rates, holidays):
    """Work out the provider's settlement line for one payment."""
    created_date = date.fromisoformat(payment["created_at"][:10])
    settlement_date = add_business_days(created_date, rng.choice([1, 2]), holidays)

    settlement_currency = merchant["settlement_currency"]
    rate = fx_rate(rates, payment["currency"], settlement_currency, settlement_date)
    gross = convert_minor_units(payment["amount_minor_units"], payment["currency"], settlement_currency, rate)

    # The fee plan is the one in force on the day the payment was made.
    plan = pick_fee_plan(fee_plans, merchant["fee_tier"], settlement_currency, created_date)
    fee = round_half_up(Decimal(gross) * Decimal(plan["percentage_fee"])) + int(plan["fixed_fee_minor_units"])

    return {
        "provider_reference": f"PRV-{number:010d}",
        "payment_id": payment["payment_id"],
        "gross_minor_units": gross,
        "fee_minor_units": fee,
        "net_minor_units": gross - fee,
        "settlement_currency": settlement_currency,
        "fx_rate": str(rate),
        "settlement_date": settlement_date.isoformat(),
    }


def generate(seed, count):
    """Make all payments and settlement lines for a seed. Returns (payments, settlement_lines)."""
    rng = random.Random(seed)  # our own random generator, started from the seed
    merchants = read_csv(SEEDS_DIR / "merchants.csv")
    merchants_by_id = {merchant["merchant_id"]: merchant for merchant in merchants}
    fee_plans = read_csv(SEEDS_DIR / "fee_plans.csv")
    holidays = load_bank_holidays()
    rates = load_rates()

    payments = make_payments(rng, merchants, count)
    lines = [
        make_settlement_line(rng, number, payment, merchants_by_id[payment["merchant_id"]], fee_plans, rates, holidays)
        for number, payment in enumerate(payments, start=1)
    ]
    return payments, lines


# ---------- Writing the output files ----------


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_files(payments, lines, output_dir):
    """Write one payments file and one settlement file per settlement date."""
    write_csv(output_dir / "payments.csv", payments, list(payments[0].keys()))

    settlement_dir = output_dir / "settlement_lines"
    for old_file in settlement_dir.glob("settlement_*.csv"):
        old_file.unlink()  # remove files from an earlier run, so days never get mixed up

    lines_by_date = {}
    for line in lines:
        lines_by_date.setdefault(line["settlement_date"], []).append(line)
    for settlement_date, day_lines in lines_by_date.items():
        write_csv(settlement_dir / f"settlement_{settlement_date}.csv", day_lines, list(day_lines[0].keys()))
    return len(lines_by_date)


def main():
    parser = argparse.ArgumentParser(description="Generate clean payments and settlement files.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--count", type=int, default=DEFAULT_PAYMENT_COUNT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    payments, lines = generate(args.seed, args.count)
    file_count = write_files(payments, lines, args.output_dir)
    print(f"Seed {args.seed}: wrote {len(payments)} payments and {len(lines)} settlement lines")
    print(f"Settlement files: {file_count}, in {args.output_dir / 'settlement_lines'}")


if __name__ == "__main__":
    main()
