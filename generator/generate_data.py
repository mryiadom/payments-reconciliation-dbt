"""Generate the data that Northgate Pay's reconciliation works on.

This program plays the outside world. It makes three things:
  - the company's own payment ledger,
  - the payment provider's daily settlement files,
  - an answer key listing every problem it planted (kept apart, used only by tests).

The same seed always gives the same files.
Run from the repo root:  python generator/generate_data.py --seed 42
"""

import argparse
import csv
import random
import shutil
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SEEDS_DIR = REPO_ROOT / "payments_recon" / "seeds"
RATES_FILE = Path(__file__).parent / "reference" / "ecb_rates.csv"
# The data is written outside the repo, like files arriving from outside the company.
DEFAULT_OUTPUT_DIR = Path.home() / "northgate_landing"
DEFAULT_ANSWER_KEY_FILE = Path.home() / "northgate_internal" / "answer_key.csv"

START_DATE = date(2026, 6, 1)
END_DATE = date(2026, 11, 30)  # the provider's files stop here
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

# Share of payments given each problem. A payment gets at most one problem, so the
# expected status of every payment is clear.
PROBLEM_RATES = {
    "fx": 0.003,
    "missing": 0.006,
    "duplicate": 0.004,
    "fee": 0.004,
    "late": 0.004,
    "messy_id": 0.003,
}
UNRECORDED_RATE = 0.002  # extra provider lines for payments we never recorded, as a share of payments
# Problems are only planted on payments up to this date, so by the end of the data the
# outcome is certain. Later payments may legitimately still be waiting to settle.
LAST_PROBLEM_DATE = date(2026, 11, 20)

# Refunds and chargebacks: share of payments, and how many of them the provider settles.
REFUND_RATE = 0.02
CHARGEBACK_RATE = 0.003
REFUND_SETTLED_SHARE = 0.8
CHARGEBACK_SETTLED_SHARE = 0.7
# Only payments up to this date are refunded, so the refund itself is made by LAST_PROBLEM_DATE.
LAST_ORIGINAL_DATE = date(2026, 11, 10)
REFUND_REFERENCE_START = 1_000_000  # provider reference numbers for refund lines, kept apart from the others


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


def calculate_fee(gross, fee_plan):
    """The plan's percentage of the gross amount, plus its fixed fee, in minor units."""
    return round_half_up(Decimal(gross) * Decimal(fee_plan["percentage_fee"])) + int(fee_plan["fixed_fee_minor_units"])


def created_date_of(payment):
    return date.fromisoformat(payment["created_at"][:10])


# ---------- Making clean data ----------


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


def build_settlement_line(reference_number, payment, merchant, settlement_date, rate, fee_plan):
    """Put one provider settlement line together from its ingredients.
    Refunds and chargebacks have no fee plan (None), so their fee is 0."""
    settlement_currency = merchant["settlement_currency"]
    gross = convert_minor_units(payment["amount_minor_units"], payment["currency"], settlement_currency, rate)
    fee = calculate_fee(gross, fee_plan) if fee_plan else 0
    return {
        "provider_reference": f"PRV-{reference_number:010d}",
        "payment_id": payment["payment_id"],
        "gross_minor_units": gross,
        "fee_minor_units": fee,
        "net_minor_units": gross - fee,
        "settlement_currency": settlement_currency,
        "fx_rate": str(rate),
        "settlement_date": settlement_date.isoformat(),
    }


def fee_plan_for(payment, merchant, reference):
    """The fee plan in force on the day the payment was made."""
    return pick_fee_plan(
        reference["fee_plans"], merchant["fee_tier"], merchant["settlement_currency"], created_date_of(payment)
    )


def make_settlement_line(rng, number, payment, reference):
    """Work out the correct provider settlement line for one payment."""
    merchant = reference["merchants_by_id"][payment["merchant_id"]]
    settlement_date = add_business_days(created_date_of(payment), rng.choice([1, 2]), reference["holidays"])
    rate = fx_rate(reference["rates"], payment["currency"], merchant["settlement_currency"], settlement_date)
    return build_settlement_line(number, payment, merchant, settlement_date, rate, fee_plan_for(payment, merchant, reference))


def build_world(seed, count):
    """Make the payments and the correct settlement line for each one.
    Returns the random generator too, so planting problems carries on from the same seed."""
    rng = random.Random(seed)  # our own random generator, started from the seed
    merchants = read_csv(SEEDS_DIR / "merchants.csv")
    reference = {
        "merchants": merchants,
        "merchants_by_id": {merchant["merchant_id"]: merchant for merchant in merchants},
        "fee_plans": read_csv(SEEDS_DIR / "fee_plans.csv"),
        "holidays": load_bank_holidays(),
        "rates": load_rates(),
    }
    payments = make_payments(rng, merchants, count)
    clean_lines = [make_settlement_line(rng, number, p, reference) for number, p in enumerate(payments, start=1)]
    return rng, payments, clean_lines, reference


def generate_clean(seed, count):
    """Payments plus a correct settlement line for every one. Nothing planted, nothing cut off."""
    _, payments, clean_lines, _ = build_world(seed, count)
    return payments, clean_lines


# ---------- Planting problems ----------


def take(pool, how_many, is_suitable=lambda index: True):
    """Remove up to how_many suitable payment numbers from the pool and return them.
    A payment taken for one problem can never be picked for another."""
    chosen = [index for index in pool if is_suitable(index)][:how_many]
    chosen_set = set(chosen)
    pool[:] = [index for index in pool if index not in chosen_set]
    return chosen


def answer_key_row(payment_id, problem_type, expected_status, detail):
    return {"payment_id": payment_id, "problem_type": problem_type, "expected_status": expected_status, "detail": detail}


def plant_problems(rng, payments, clean_lines, reference):
    """Spoil some of the provider's lines on purpose and record each change in an answer key.
    Returns (provider_lines, answer_key)."""
    merchants_by_id = reference["merchants_by_id"]
    holidays = reference["holidays"]
    count = len(payments)
    delivered = {index: [line] for index, line in enumerate(clean_lines)}  # lines sent per payment
    extra_lines = []  # lines for payments we never recorded
    answer_key = []
    next_reference = count + 1  # reference numbers for extra lines the provider sends

    def note(payment_id, problem_type, expected_status, detail):
        answer_key.append(answer_key_row(payment_id, problem_type, expected_status, detail))

    def merchant_of(index):
        return merchants_by_id[payments[index]["merchant_id"]]

    def is_cross_currency(index):
        return payments[index]["currency"] != merchant_of(index)["settlement_currency"]

    pool = [i for i, p in enumerate(payments) if created_date_of(p) <= LAST_PROBLEM_DATE]
    rng.shuffle(pool)
    wanted = {name: round(rate * count) for name, rate in PROBLEM_RATES.items()}
    chosen = {name: take(pool, wanted[name], is_cross_currency if name == "fx" else lambda index: True) for name in PROBLEM_RATES}

    for i in chosen["missing"]:
        delivered[i] = []
        note(payments[i]["payment_id"], "missing", "Missing settlement", "The provider sent no settlement line.")

    for i in chosen["duplicate"]:
        line = delivered[i][0]
        second = dict(line)
        second["provider_reference"] = f"PRV-{next_reference:010d}"
        next_reference += 1
        second["settlement_date"] = add_business_days(date.fromisoformat(line["settlement_date"]), 1, holidays).isoformat()
        delivered[i].append(second)
        note(payments[i]["payment_id"], "duplicate", "Duplicate settlement", "Settled twice, a business day apart.")

    for i in chosen["fee"]:
        line, payment, merchant = delivered[i][0], payments[i], merchant_of(i)
        wrong_fee = line["fee_minor_units"] * 2
        detail = "Fee charged twice."
        if rng.random() < 0.5:
            other_tier = rng.choice([t for t in ("standard", "volume", "premium") if t != merchant["fee_tier"]])
            other_plan = pick_fee_plan(
                reference["fee_plans"], other_tier, merchant["settlement_currency"], created_date_of(payment)
            )
            other_fee = calculate_fee(line["gross_minor_units"], other_plan)
            if abs(other_fee - line["fee_minor_units"]) >= 2:  # big enough to be clearly wrong
                wrong_fee, detail = other_fee, f"Fee taken from the {other_tier} plan, not the merchant's {merchant['fee_tier']} plan."
        line["fee_minor_units"] = wrong_fee
        line["net_minor_units"] = line["gross_minor_units"] - wrong_fee
        note(payment["payment_id"], "fee", "Amount mismatch", detail)

    for i in chosen["fx"]:
        line, payment, merchant = delivered[i][0], payments[i], merchant_of(i)
        factor = Decimal(rng.choice(["1.01", "1.015", "1.02", "0.99", "0.985", "0.98"]))
        wrong_rate = (Decimal(line["fx_rate"]) * factor).quantize(FX_RATE_PLACES, rounding=ROUND_HALF_UP)
        # The provider's gross and fee follow its own wrong rate, so only the rate itself is off.
        delivered[i] = [
            build_settlement_line(
                i + 1, payment, merchant, date.fromisoformat(line["settlement_date"]), wrong_rate,
                fee_plan_for(payment, merchant, reference),
            )
        ]
        note(payment["payment_id"], "fx", "FX mismatch", f"Provider rate {factor} times the ECB-derived rate.")

    for i in chosen["late"]:
        payment, merchant = payments[i], merchant_of(i)
        late_date = add_business_days(created_date_of(payment), rng.choice([3, 4]), holidays)
        rate = fx_rate(reference["rates"], payment["currency"], merchant["settlement_currency"], late_date)
        delivered[i] = [
            build_settlement_line(i + 1, payment, merchant, late_date, rate, fee_plan_for(payment, merchant, reference))
        ]
        note(payment["payment_id"], "late", "Late settlement", "Settled 3 or 4 business days after the payment.")

    for i in chosen["messy_id"]:
        line = delivered[i][0]
        clean_id = line["payment_id"]
        line["payment_id"] = rng.choice([f" {clean_id}", f"{clean_id} ", clean_id.lower(), f"  {clean_id.lower()} "])
        note(clean_id, "messy_id", "Matched", f"The provider wrote the id as {line['payment_id']!r}. It should still match.")

    for k in range(round(UNRECORDED_RATE * count)):
        merchant = rng.choice(reference["merchants"])
        currency = merchant["settlement_currency"]
        low, high = AMOUNT_RANGES[currency]
        made_up_payment = {"payment_id": f"PAY-9{k + 1:05d}", "amount_minor_units": rng.randint(low, high), "currency": currency}
        created = START_DATE + timedelta(days=rng.randrange((LAST_PROBLEM_DATE - START_DATE).days + 1))
        settled = add_business_days(created, rng.choice([1, 2]), holidays)
        plan = pick_fee_plan(reference["fee_plans"], merchant["fee_tier"], currency, created)
        extra_lines.append(
            build_settlement_line(next_reference, made_up_payment, merchant, settled, Decimal(1).quantize(FX_RATE_PLACES), plan)
        )
        next_reference += 1
        note(made_up_payment["payment_id"], "unrecorded", "Unrecorded settlement", "A settlement line for a payment we never recorded.")

    provider_lines = [line for lines in delivered.values() for line in lines] + extra_lines
    return provider_lines, answer_key


def add_refunds_and_chargebacks(rng, payments, answer_key, reference):
    """Refund or charge back some payments that had no other problem.
    Both are negative amounts linked to the original payment, and the provider takes no fee on them.
    Some are settled (a negative settlement line) and some never are, which should show as missing.
    Returns (extra_ledger_rows, extra_provider_lines) and adds rows to the answer key."""
    holidays = reference["holidays"]
    has_a_problem = {row["payment_id"] for row in answer_key}
    eligible = [p for p in payments if created_date_of(p) <= LAST_ORIGINAL_DATE and p["payment_id"] not in has_a_problem]
    refund_count = round(REFUND_RATE * len(payments))
    chargeback_count = round(CHARGEBACK_RATE * len(payments))
    originals = rng.sample(eligible, refund_count + chargeback_count)

    ledger_rows, provider_lines = [], []
    for number, original in enumerate(originals, start=1):
        is_refund = number <= refund_count
        kind = "refund" if is_refund else "chargeback"
        prefix = "REF" if is_refund else "CBK"
        settled_share = REFUND_SETTLED_SHARE if is_refund else CHARGEBACK_SETTLED_SHARE
        item_number = number if is_refund else number - refund_count

        created_day = created_date_of(original) + timedelta(days=rng.randint(1, 10))
        created_at = datetime.combine(created_day, datetime.min.time()) + timedelta(seconds=rng.randrange(86_400))
        item = {
            "payment_id": f"{prefix}-{item_number:06d}",
            "merchant_id": original["merchant_id"],
            "amount_minor_units": -original["amount_minor_units"],  # money going back out
            "currency": original["currency"],
            "created_at": created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "payment_type": kind,
            "linked_payment_id": original["payment_id"],
        }
        ledger_rows.append(item)

        if rng.random() < settled_share:
            merchant = reference["merchants_by_id"][item["merchant_id"]]
            settlement_date = add_business_days(created_day, rng.choice([1, 2]), holidays)
            rate = fx_rate(reference["rates"], item["currency"], merchant["settlement_currency"], settlement_date)
            provider_lines.append(
                build_settlement_line(REFUND_REFERENCE_START + number, item, merchant, settlement_date, rate, None)
            )
            answer_key.append(answer_key_row(item["payment_id"], f"{kind}_settled", "Matched", f"A {kind} settled as a negative line."))
        else:
            answer_key.append(
                answer_key_row(item["payment_id"], f"{kind}_unsettled", "Missing settlement", f"A {kind} the provider never settled.")
            )
    return ledger_rows, provider_lines


def generate(seed, count):
    """Make everything for a seed. Returns (ledger, provider_lines, answer_key)."""
    rng, payments, clean_lines, reference = build_world(seed, count)
    provider_lines, answer_key = plant_problems(rng, payments, clean_lines, reference)
    refund_rows, refund_lines = add_refunds_and_chargebacks(rng, payments, answer_key, reference)
    ledger = sorted(payments + refund_rows, key=lambda row: (row["created_at"], row["payment_id"]))
    provider_lines += refund_lines
    # The provider's files stop at END_DATE. Payments whose line would fall after that
    # have not settled yet, so they are simply still waiting (Pending).
    provider_lines = [line for line in provider_lines if line["settlement_date"] <= END_DATE.isoformat()]
    provider_lines.sort(key=lambda line: (line["settlement_date"], line["provider_reference"]))
    return ledger, provider_lines, answer_key


# ---------- Writing the output files ----------


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_files(payments, provider_lines, output_dir):
    """Write the files the way they would arrive: the ledger, the provider's daily files and the ECB rates."""
    write_csv(output_dir / "ledger" / "payments.csv", payments, list(payments[0].keys()))

    provider_dir = output_dir / "provider"
    for old_file in provider_dir.glob("settlement_*.csv"):
        old_file.unlink()  # remove files from an earlier run, so days never get mixed up

    lines_by_date = {}
    for line in provider_lines:
        lines_by_date.setdefault(line["settlement_date"], []).append(line)
    for settlement_date, day_lines in lines_by_date.items():
        write_csv(provider_dir / f"settlement_{settlement_date}.csv", day_lines, list(day_lines[0].keys()))

    (output_dir / "ecb").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RATES_FILE, output_dir / "ecb" / "ecb_rates.csv")
    return len(lines_by_date)


def write_answer_key(answer_key, answer_key_file):
    write_csv(answer_key_file, answer_key, ["payment_id", "problem_type", "expected_status", "detail"])


def main():
    parser = argparse.ArgumentParser(description="Generate payments, provider settlement files and an answer key.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--count", type=int, default=DEFAULT_PAYMENT_COUNT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--answer-key-file", type=Path, default=DEFAULT_ANSWER_KEY_FILE)
    args = parser.parse_args()

    payments, provider_lines, answer_key = generate(args.seed, args.count)
    file_count = write_files(payments, provider_lines, args.output_dir)
    write_answer_key(answer_key, args.answer_key_file)
    print(f"Seed {args.seed}: {len(payments)} payments, {len(provider_lines)} provider lines in {file_count} files")
    print(f"Data written to {args.output_dir}")
    print(f"Answer key ({len(answer_key)} rows) written to {args.answer_key_file}")


if __name__ == "__main__":
    main()
