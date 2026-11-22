"""Generate the synthetic data for the payments reconciliation project.

Everything here is invented. The script creates:

- an internal payments ledger (one CSV per calendar day)
- the payment provider's settlement files (one CSV per UK business day)
- daily reference FX rates in the ECB style (euros as the base currency)
- a merchant list
- an answer key listing the status every record SHOULD get, used only by tests

It also plants known problems (missing, duplicate, late, wrong fee, wrong FX,
unrecorded settlements) so the reconciliation can be proved against the answer key.

Run from the repo root:

    python generator/generate_data.py

The same seed always produces exactly the same files.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

START_DATE = date(2026, 6, 1)   # first day of payments
AS_OF_DATE = date(2026, 11, 20)  # last day of data (a Friday)
SETTLEMENT_DAYS = 2              # provider promises to settle within 2 business days
DEFAULT_SEED = 42
PAYMENTS_PER_DAY = 290           # roughly 50,000 payments over the period

# Minor units: pence and cents have 2 decimal places, yen has none.
CURRENCY_DECIMALS = {"GBP": 2, "EUR": 2, "USD": 2, "SEK": 2, "JPY": 0}

# Starting FX rates: units of each currency per 1 euro (the ECB convention).
START_RATES_PER_EUR = {"GBP": 0.8550, "USD": 1.0850, "SEK": 11.30, "JPY": 165.0}
DAILY_FX_VOLATILITY = 0.004      # about 0.4% move per day

UK_BANK_HOLIDAYS_2026 = [
    (date(2026, 1, 1), "New Year's Day"),
    (date(2026, 4, 3), "Good Friday"),
    (date(2026, 4, 6), "Easter Monday"),
    (date(2026, 5, 4), "Early May bank holiday"),
    (date(2026, 5, 25), "Spring bank holiday"),
    (date(2026, 8, 31), "Summer bank holiday"),
    (date(2026, 12, 25), "Christmas Day"),
    (date(2026, 12, 28), "Boxing Day (substitute day)"),
]
UK_HOLIDAY_DATES = {d for d, _ in UK_BANK_HOLIDAYS_2026}

# Fee plans. STANDARD goes up from 1.40% to 1.50% on 1 September 2026.
FEE_PLANS = [
    # plan_code, valid_from, valid_to, percentage fee, fixed fee (minor units), chargeback fee (minor units)
    ("STANDARD", date(2026, 1, 1), date(2026, 8, 31), Decimal("1.40"), 20, 1500),
    ("STANDARD", date(2026, 9, 1), date(9999, 12, 31), Decimal("1.50"), 20, 1500),
    ("VOLUME", date(2026, 1, 1), date(9999, 12, 31), Decimal("0.95"), 10, 1500),
    ("PREMIUM", date(2026, 1, 1), date(9999, 12, 31), Decimal("2.10"), 25, 1500),
]

# How often each problem is planted.
RATE_MISSING = 0.006
RATE_DUPLICATE = 0.004
RATE_AMOUNT_MISMATCH = 0.005
RATE_FX_MISMATCH = 0.015   # only applies to payments in a different currency from settlement
RATE_LATE = 0.006
RATE_ID_NOISE = 0.010      # payment id with stray spaces or lower case: should still match
UNRECORDED_LINES = 60      # settlement lines for payments we never recorded

REFUND_RATE = 0.03
CHARGEBACK_RATE = 0.004

MERCHANT_NAMES = [
    "Harbour Lane Coffee", "Northfield Books", "Copper Kettle Bakery", "Brightwater Cycles",
    "Elm Street Florist", "Kingsway Opticians", "Riverside Gym", "Bramble & Rye",
    "Old Mill Hardware", "Lantern Theatre", "Seaview Surf Shop", "Thistle Home Goods",
    "Foxglove Pharmacy", "Oakwood Pet Supplies", "Highgate Records", "Willow Yoga Studio",
    "Cobalt Electronics", "Marlow Tailoring", "Pebble Toy Shop", "Greenleaf Grocers",
    "Café Lumière", "Atelier Nord", "Berliner Buchladen", "Haven Fietsen",
    "Ostra Design", "Lisboa Ceramics", "Dublin Tea Rooms", "Rhein Outdoor",
    "Maison Verte", "Kanal Coffee Roasters", "Amstel Prints", "Galway Woollens",
    "Liberty Street Deli", "Pine Ridge Outfitters", "Golden Gate Bikes", "Maple Avenue Salon",
    "Lakeshore Games", "Hudson Paper Co", "Sunset Skate", "Prairie Candle Works",
]

# country, settlement currency, how many merchants, currency mix of their customers
MERCHANT_GROUPS = [
    ("GB", "GBP", 20, {"GBP": 75, "EUR": 10, "USD": 8, "SEK": 4, "JPY": 3}),
    ("IE", "EUR", 3, {"EUR": 75, "GBP": 8, "USD": 8, "SEK": 6, "JPY": 3}),
    ("DE", "EUR", 3, {"EUR": 75, "GBP": 8, "USD": 8, "SEK": 6, "JPY": 3}),
    ("FR", "EUR", 3, {"EUR": 75, "GBP": 8, "USD": 8, "SEK": 6, "JPY": 3}),
    ("NL", "EUR", 3, {"EUR": 75, "GBP": 8, "USD": 8, "SEK": 6, "JPY": 3}),
    ("US", "USD", 8, {"USD": 80, "EUR": 8, "GBP": 6, "JPY": 4, "SEK": 2}),
]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def round_half_away(value: Decimal) -> int:
    """Round to a whole number, halves away from zero (the same as BigQuery's ROUND)."""
    rounded = abs(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(rounded) if value >= 0 else -int(rounded)


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in UK_HOLIDAY_DATES


def add_business_days(d: date, n: int) -> date:
    """Move forward n UK business days from d (d itself is day 0)."""
    current = d
    counted = 0
    while counted < n:
        current += timedelta(days=1)
        if is_business_day(current):
            counted += 1
    return current


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Merchant:
    merchant_id: str
    merchant_name: str
    country: str
    settlement_currency: str
    fee_plan_code: str
    onboarded_date: date
    currency_mix: dict
    weight: float


@dataclass
class Payment:
    merchant: Merchant
    payment_type: str            # PAYMENT, REFUND or CHARGEBACK
    currency: str
    amount_minor: int            # negative for refunds and chargebacks
    created_at: datetime
    card_scheme: str
    original: "Payment | None" = None
    payment_id: str = ""
    planted_issue: str = "none"
    expected_status: str = ""
    lines: list = field(default_factory=list)

    @property
    def created_date(self) -> date:
        return self.created_at.date()


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def build_fx_rates(rng: random.Random) -> dict:
    """Daily rates per euro on weekdays, as a random walk. Returns {date: {currency: rate}}."""
    rates = {}
    current = {ccy: Decimal(str(r)) for ccy, r in START_RATES_PER_EUR.items()}
    for d in daterange(START_DATE - timedelta(days=7), AS_OF_DATE):
        if d.weekday() >= 5:  # the ECB publishes no rates at weekends
            continue
        for ccy in current:
            move = Decimal(str(math.exp(rng.gauss(0, DAILY_FX_VOLATILITY))))
            current[ccy] = current[ccy] * move
        # JPY rates are published to 2 decimal places, the others to 4.
        rates[d] = {
            ccy: (val.quantize(Decimal("0.01")) if ccy == "JPY" else val.quantize(Decimal("0.0001")))
            for ccy, val in current.items()
        }
        rates[d]["EUR"] = Decimal("1")
    return rates


def rate_on(rates: dict, d: date) -> dict:
    """The reference rates that apply on a date: that day's, or the last published before it."""
    while d not in rates:
        d -= timedelta(days=1)
    return rates[d]


def cross_rate(rates: dict, d: date, from_ccy: str, to_ccy: str) -> Decimal:
    """How many units of to_ccy one unit of from_ccy buys, worked out through the euro."""
    day_rates = rate_on(rates, d)
    return (day_rates[to_ccy] / day_rates[from_ccy]).quantize(Decimal("0.000001"))


def build_merchants(rng: random.Random) -> list[Merchant]:
    merchants = []
    plans = ["STANDARD"] * 26 + ["VOLUME"] * 8 + ["PREMIUM"] * 6
    rng.shuffle(plans)
    names = iter(MERCHANT_NAMES)
    number = 1
    for country, settle_ccy, count, mix in MERCHANT_GROUPS:
        for _ in range(count):
            merchants.append(
                Merchant(
                    merchant_id=f"M{number:03d}",
                    merchant_name=next(names),
                    country=country,
                    settlement_currency=settle_ccy,
                    fee_plan_code=plans[number - 1],
                    onboarded_date=date(2024, 1, 1) + timedelta(days=rng.randint(0, 800)),
                    currency_mix=mix,
                    weight=rng.lognormvariate(0, 0.8),
                )
            )
            number += 1
    return merchants


def random_amount_minor(rng: random.Random, rates: dict, d: date, ccy: str) -> int:
    """A realistic basket value, picked in pounds then converted to the payment currency."""
    gbp = min(max(rng.lognormvariate(math.log(35), 0.9), 1.0), 2000.0)
    major = Decimal(str(gbp)) * cross_rate(rates, d, "GBP", ccy)
    return max(round_half_away(major * (10 ** CURRENCY_DECIMALS[ccy])), 1)


def build_payments(rng: random.Random, merchants: list[Merchant], rates: dict) -> list[Payment]:
    weights = [m.weight for m in merchants]
    schemes = ["VISA", "MASTERCARD", "AMEX"]
    payments = []
    for d in daterange(START_DATE, AS_OF_DATE):
        daily = PAYMENTS_PER_DAY if d.weekday() < 5 else int(PAYMENTS_PER_DAY * 0.8)
        for _ in range(daily):
            merchant = rng.choices(merchants, weights=weights)[0]
            ccy = rng.choices(list(merchant.currency_mix), weights=list(merchant.currency_mix.values()))[0]
            created = datetime.combine(d, time(0, 0), tzinfo=timezone.utc) + timedelta(
                seconds=rng.randint(0, 86399)
            )
            payments.append(
                Payment(
                    merchant=merchant,
                    payment_type="PAYMENT",
                    currency=ccy,
                    amount_minor=random_amount_minor(rng, rates, d, ccy),
                    created_at=created,
                    card_scheme=rng.choices(schemes, weights=[55, 35, 10])[0],
                )
            )

    # Refunds and chargebacks point back at an earlier payment.
    extras = []
    for p in payments:
        roll = rng.random()
        if roll < REFUND_RATE:
            delay, kind = rng.randint(1, 20), "REFUND"
            amount = p.amount_minor if rng.random() < 0.6 else max(p.amount_minor // rng.randint(2, 4), 1)
        elif roll < REFUND_RATE + CHARGEBACK_RATE:
            delay, kind, amount = rng.randint(15, 45), "CHARGEBACK", p.amount_minor
        else:
            continue
        created = p.created_at + timedelta(days=delay, seconds=rng.randint(0, 3600))
        if created.date() > AS_OF_DATE:
            continue
        extras.append(
            Payment(
                merchant=p.merchant,
                payment_type=kind,
                currency=p.currency,
                amount_minor=-amount,
                created_at=created,
                card_scheme=p.card_scheme,
                original=p,
            )
        )

    everything = sorted(payments + extras, key=lambda x: x.created_at)
    for i, p in enumerate(everything, start=1):
        p.payment_id = f"PAY-{i:07d}"
    return everything


def fee_plan_for(plan_code: str, d: date):
    for code, valid_from, valid_to, pct, fixed, chargeback in FEE_PLANS:
        if code == plan_code and valid_from <= d <= valid_to:
            return pct, fixed, chargeback
    raise ValueError(f"No fee plan {plan_code} on {d}")


def expected_fee(payment: Payment, gross_minor: int, pct: Decimal, fixed: int, chargeback: int) -> int:
    """Fee rules: payments pay % + fixed; refunds pay nothing; chargebacks pay a flat fee."""
    if payment.payment_type == "PAYMENT":
        return round_half_away(Decimal(gross_minor) * pct / Decimal(100)) + fixed
    if payment.payment_type == "CHARGEBACK":
        return chargeback
    return 0


def plant_issues(rng: random.Random, payments: list[Payment]) -> None:
    """Give a small share of records exactly one known problem each."""
    for p in payments:
        due = add_business_days(p.created_date, SETTLEMENT_DAYS)
        roll = rng.random()
        cross_currency = p.currency != p.merchant.settlement_currency
        big_enough = p.amount_minor > 0  # amount checks only on positive payments

        thresholds = [
            ("missing", RATE_MISSING, due <= AS_OF_DATE),
            ("duplicate", RATE_DUPLICATE, due < AS_OF_DATE),
            ("amount_mismatch", RATE_AMOUNT_MISMATCH, p.payment_type == "PAYMENT" and big_enough),
            ("fx_mismatch", RATE_FX_MISMATCH, p.payment_type == "PAYMENT" and cross_currency),
            ("late", RATE_LATE, add_business_days(p.created_date, 6) <= AS_OF_DATE),
            ("id_noise", RATE_ID_NOISE, True),
        ]
        cumulative = 0.0
        for issue, rate, allowed in thresholds:
            cumulative += rate
            if roll < cumulative:
                if allowed:
                    p.planted_issue = issue
                break


def build_settlement_lines(rng: random.Random, payments: list[Payment], rates: dict) -> list[dict]:
    lines = []
    for p in payments:
        merchant = p.merchant
        issue = p.planted_issue
        due = add_business_days(p.created_date, SETTLEMENT_DAYS)

        if issue == "late":
            settle_date = add_business_days(p.created_date, rng.randint(SETTLEMENT_DAYS + 1, 6))
        else:
            settle_date = add_business_days(p.created_date, rng.randint(1, SETTLEMENT_DAYS))

        # Work out what the status should be.
        if issue == "missing":
            p.expected_status = "MISSING"
            continue
        if settle_date > AS_OF_DATE:
            p.expected_status = "PENDING" if due > AS_OF_DATE else "MISSING"
            continue
        p.expected_status = {
            "duplicate": "DUPLICATE",
            "amount_mismatch": "AMOUNT_MISMATCH",
            "fx_mismatch": "FX_MISMATCH",
            "late": "LATE",
        }.get(issue, "MATCHED")

        settle_ccy = merchant.settlement_currency
        fx = cross_rate(rates, p.created_date, p.currency, settle_ccy)
        if issue == "fx_mismatch":
            off_by = Decimal(str(rng.uniform(0.01, 0.03))) * (1 if rng.random() < 0.5 else -1)
            fx = (fx * (Decimal(1) + off_by)).quantize(Decimal("0.000001"))

        scale = Decimal(10) ** (CURRENCY_DECIMALS[settle_ccy] - CURRENCY_DECIMALS[p.currency])
        gross = round_half_away(Decimal(p.amount_minor) * scale * fx)

        pct, fixed, chargeback = fee_plan_for(merchant.fee_plan_code, p.created_date)
        fee = expected_fee(p, gross, pct, fixed, chargeback)
        if issue == "amount_mismatch":
            if merchant.fee_plan_code == "STANDARD" and p.created_date >= date(2026, 9, 1) and gross >= 2000:
                old_pct, old_fixed, _ = fee_plan_for("STANDARD", date(2026, 8, 31))
                fee = round_half_away(Decimal(gross) * old_pct / Decimal(100)) + old_fixed
                p.planted_issue = "amount_mismatch_old_fee_plan"
            else:
                fee = fee * 2
                p.planted_issue = "amount_mismatch_fee_charged_twice"

        provider_payment_id = p.payment_id
        if issue == "id_noise":
            provider_payment_id = p.payment_id.lower() if rng.random() < 0.5 else p.payment_id + "  "

        line = {
            "settlement_date": settle_date,
            "merchant_id": merchant.merchant_id,
            "payment_id": provider_payment_id,
            "transaction_type": {"PAYMENT": "CAPTURE"}.get(p.payment_type, p.payment_type),
            "presentment_currency": p.currency,
            "presentment_amount_minor": p.amount_minor,
            "settlement_currency": settle_ccy,
            "fx_rate": fx,
            "gross_amount_minor": gross,
            "fee_amount_minor": fee,
            "net_amount_minor": gross - fee,
        }
        lines.append(line)
        p.lines.append(line)

        if issue == "duplicate":
            again = dict(line)
            next_day = add_business_days(settle_date, rng.randint(0, 1))
            again["settlement_date"] = min(next_day, AS_OF_DATE)
            lines.append(again)
            p.lines.append(again)

    # Lines the provider settled that are not in our ledger at all.
    business_days = [d for d in daterange(START_DATE + timedelta(days=3), AS_OF_DATE) if is_business_day(d)]
    merchants = sorted({p.merchant.merchant_id: p.merchant for p in payments}.values(),
                       key=lambda m: m.merchant_id)
    unrecorded = []
    for i in range(UNRECORDED_LINES):
        merchant = rng.choice(merchants)
        settle_ccy = merchant.settlement_currency
        settle_date = rng.choice(business_days)
        gross = rng.randint(500, 15000)  # 5.00 to 150.00 in the settlement currency
        pct, fixed, _ = fee_plan_for(merchant.fee_plan_code, settle_date)
        fee = round_half_away(Decimal(gross) * pct / Decimal(100)) + fixed
        line = {
            "settlement_date": settle_date,
            "merchant_id": merchant.merchant_id,
            "payment_id": f"PAY-9{i + 1:06d}",
            "transaction_type": "CAPTURE",
            "presentment_currency": settle_ccy,
            "presentment_amount_minor": gross,
            "settlement_currency": settle_ccy,
            "fx_rate": Decimal("1.000000"),
            "gross_amount_minor": gross,
            "fee_amount_minor": fee,
            "net_amount_minor": gross - fee,
        }
        lines.append(line)
        unrecorded.append(line)

    # Provider references follow the order the provider wrote its files.
    lines.sort(key=lambda x: (x["settlement_date"], x["merchant_id"], x["payment_id"].strip().upper()))
    for i, line in enumerate(lines, start=1):
        line["provider_ref"] = f"STL-{i:08d}"
    for line in unrecorded:
        line["unrecorded"] = True
    return lines


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def write_all(out: Path, seeds_out: Path, merchants, payments, lines, rates) -> None:
    if out.exists():
        shutil.rmtree(out)

    # Payments ledger: one file per calendar day.
    by_day = {}
    for p in payments:
        by_day.setdefault(p.created_date, []).append(p)
    for d in daterange(START_DATE, AS_OF_DATE):
        rows = [
            [
                p.payment_id,
                p.merchant.merchant_id,
                p.payment_type,
                p.original.payment_id if p.original else "",
                p.currency,
                p.amount_minor,
                p.created_at.strftime("%Y-%m-%d %H:%M:%S+00:00"),
                p.card_scheme,
            ]
            for p in by_day.get(d, [])
        ]
        write_csv(
            out / "payments" / f"payments_{d:%Y%m%d}.csv",
            ["payment_id", "merchant_id", "payment_type", "original_payment_id", "currency",
             "amount_minor", "created_at", "card_scheme"],
            rows,
        )

    # Settlement files: one per UK business day.
    by_settle_day = {}
    for line in lines:
        by_settle_day.setdefault(line["settlement_date"], []).append(line)
    for d in daterange(START_DATE, AS_OF_DATE):
        if not is_business_day(d):
            continue
        rows = [
            [
                line["provider_ref"], line["settlement_date"].isoformat(), line["merchant_id"],
                line["payment_id"], line["transaction_type"], line["presentment_currency"],
                line["presentment_amount_minor"], line["settlement_currency"], str(line["fx_rate"]),
                line["gross_amount_minor"], line["fee_amount_minor"], line["net_amount_minor"],
            ]
            for line in by_settle_day.get(d, [])
        ]
        write_csv(
            out / "settlements" / f"settlement_{d:%Y%m%d}.csv",
            ["provider_ref", "settlement_date", "merchant_id", "payment_id", "transaction_type",
             "presentment_currency", "presentment_amount_minor", "settlement_currency", "fx_rate",
             "gross_amount_minor", "fee_amount_minor", "net_amount_minor"],
            rows,
        )

    # FX rates: long format, one row per currency per publishing day.
    fx_rows = [
        [d.isoformat(), ccy, str(rate)]
        for d, day_rates in sorted(rates.items())
        for ccy, rate in sorted(day_rates.items())
        if ccy != "EUR"
    ]
    write_csv(out / "fx_rates" / "fx_rates.csv", ["rate_date", "currency", "rate_per_eur"], fx_rows)

    write_csv(
        out / "merchants" / "merchants.csv",
        ["merchant_id", "merchant_name", "country", "settlement_currency", "fee_plan_code", "onboarded_date"],
        [[m.merchant_id, m.merchant_name, m.country, m.settlement_currency, m.fee_plan_code,
          m.onboarded_date.isoformat()] for m in merchants],
    )

    # Answer key: one row per payment, plus one per unrecorded settlement line.
    key_rows = [[p.payment_id, "", p.expected_status, p.planted_issue] for p in payments]
    key_rows += [
        ["", line["provider_ref"], "UNRECORDED", "unrecorded_settlement"]
        for line in lines if line.get("unrecorded")
    ]
    write_csv(out / "answer_key" / "answer_key.csv",
              ["payment_id", "provider_ref", "expected_status", "planted_issue"], key_rows)

    # Reference tables that become dbt seeds.
    write_csv(
        seeds_out / "fee_plans.csv",
        ["fee_plan_code", "valid_from", "valid_to", "percentage_fee", "fixed_fee_minor", "chargeback_fee_minor"],
        [[c, f.isoformat(), t.isoformat(), str(p), fx, cb] for c, f, t, p, fx, cb in FEE_PLANS],
    )
    write_csv(seeds_out / "currencies.csv", ["currency_code", "decimal_places"],
              [[c, dp] for c, dp in CURRENCY_DECIMALS.items()])
    write_csv(seeds_out / "uk_bank_holidays.csv", ["holiday_date", "holiday_name"],
              [[d.isoformat(), name] for d, name in UK_BANK_HOLIDAYS_2026])


def generate(seed: int, out: Path, seeds_out: Path) -> dict:
    rng = random.Random(seed)
    rates = build_fx_rates(rng)
    merchants = build_merchants(rng)
    payments = build_payments(rng, merchants, rates)
    plant_issues(rng, payments)
    lines = build_settlement_lines(rng, payments, rates)
    write_all(out, seeds_out, merchants, payments, lines, rates)

    summary = {}
    for p in payments:
        summary[p.expected_status] = summary.get(p.expected_status, 0) + 1
    summary["UNRECORDED"] = UNRECORDED_LINES
    summary["payments"] = len(payments)
    summary["settlement_lines"] = len(lines)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=Path("data"))
    parser.add_argument("--seeds-out", type=Path, default=Path("payments_recon/seeds"))
    args = parser.parse_args()
    summary = generate(args.seed, args.out, args.seeds_out)
    for key, value in sorted(summary.items()):
        print(f"{key:>20}: {value:,}")


if __name__ == "__main__":
    main()
