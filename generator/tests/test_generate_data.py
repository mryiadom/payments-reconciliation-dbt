"""Tests for the building blocks and the clean data. Whole-run tests use a small payment count to stay fast."""

from datetime import date
from decimal import Decimal

import pytest
from generate_data import (
    SEEDS_DIR,
    add_business_days,
    convert_minor_units,
    generate_clean,
    is_business_day,
    load_bank_holidays,
    pick_fee_plan,
    read_csv,
    round_half_up,
    write_files,
)

SMALL_COUNT = 300


@pytest.fixture(scope="module")
def clean_data():
    return generate_clean(seed=42, count=SMALL_COUNT)


# ---------- Building blocks ----------


def test_round_half_up_rounds_a_half_upwards():
    assert round_half_up(Decimal("2.5")) == 3
    assert round_half_up(Decimal("2.4")) == 2


def test_convert_to_jpy_has_no_decimals():
    # 100.00 GBP at 190.5 yen per pound is 19,050 yen, a whole number.
    assert convert_minor_units(10_000, "GBP", "JPY", Decimal("190.5")) == 19_050


def test_convert_from_jpy_to_pence():
    # 19,050 yen at 0.00524934 pounds per yen is about 100.00 GBP, which is 10,000 pence.
    assert convert_minor_units(19_050, "JPY", "GBP", Decimal("0.00524934")) == 10_000


def test_convert_rounds_half_up():
    assert convert_minor_units(1, "GBP", "GBP", Decimal("0.5")) == 1


def test_business_days_skip_weekends_and_holidays():
    holidays = load_bank_holidays()
    # Friday 28 Aug 2026 plus one business day: Monday 31 Aug is a bank holiday, so Tuesday 1 Sept.
    assert add_business_days(date(2026, 8, 28), 1, holidays) == date(2026, 9, 1)
    assert not is_business_day(date(2026, 8, 31), holidays)
    assert not is_business_day(date(2026, 6, 6), holidays)  # a Saturday


def test_fee_plan_changes_on_1_september():
    fee_plans = read_csv(SEEDS_DIR / "fee_plans.csv")
    before = pick_fee_plan(fee_plans, "standard", "GBP", date(2026, 8, 31))
    after = pick_fee_plan(fee_plans, "standard", "GBP", date(2026, 9, 1))
    assert before["fee_plan_id"] == "STD_GBP_V1"
    assert after["fee_plan_id"] == "STD_GBP_V2"


# ---------- Whole run ----------


def test_same_seed_gives_same_data(clean_data):
    assert generate_clean(seed=42, count=SMALL_COUNT) == clean_data


def test_different_seed_gives_different_data(clean_data):
    assert generate_clean(seed=43, count=SMALL_COUNT) != clean_data


def test_makes_the_requested_number_of_payments(clean_data):
    payments, lines = clean_data
    assert len(payments) == SMALL_COUNT
    assert len(lines) == SMALL_COUNT


def test_every_payment_has_exactly_one_settlement_line(clean_data):
    payments, lines = clean_data
    line_ids = [line["payment_id"] for line in lines]
    assert sorted(line_ids) == sorted(payment["payment_id"] for payment in payments)


def test_ids_are_unique(clean_data):
    payments, lines = clean_data
    assert len({p["payment_id"] for p in payments}) == len(payments)
    assert len({line["provider_reference"] for line in lines}) == len(lines)


def test_net_is_gross_minus_fee(clean_data):
    _, lines = clean_data
    for line in lines:
        assert line["net_minor_units"] == line["gross_minor_units"] - line["fee_minor_units"]
        assert line["net_minor_units"] > 0


def test_settlement_is_on_a_business_day_within_two_days(clean_data):
    payments, lines = clean_data
    holidays = load_bank_holidays()
    created = {p["payment_id"]: date.fromisoformat(p["created_at"][:10]) for p in payments}
    for line in lines:
        settled = date.fromisoformat(line["settlement_date"])
        assert is_business_day(settled, holidays)
        allowed = {add_business_days(created[line["payment_id"]], n, holidays) for n in (1, 2)}
        assert settled in allowed


def test_settlement_currency_is_the_merchants_currency(clean_data):
    payments, lines = clean_data
    merchants = {m["merchant_id"]: m for m in read_csv(SEEDS_DIR / "merchants.csv")}
    merchant_of = {p["payment_id"]: p["merchant_id"] for p in payments}
    for line in lines:
        assert line["settlement_currency"] == merchants[merchant_of[line["payment_id"]]]["settlement_currency"]


def test_files_are_written_one_per_settlement_day(clean_data, tmp_path):
    payments, lines = clean_data
    file_count = write_files(payments, lines, tmp_path)
    assert (tmp_path / "ledger" / "payments.csv").exists()
    assert (tmp_path / "ecb" / "ecb_rates.csv").exists()
    assert len(list((tmp_path / "provider").glob("settlement_*.csv"))) == file_count
    assert file_count == len({line["settlement_date"] for line in lines})
