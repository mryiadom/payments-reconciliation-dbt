"""Tests that every planted problem really has the property its answer key row claims."""

from collections import Counter
from datetime import date

import pytest
from generate_data import (
    END_DATE,
    LAST_PROBLEM_DATE,
    SEEDS_DIR,
    add_business_days,
    calculate_fee,
    fx_rate,
    generate,
    load_bank_holidays,
    load_rates,
    pick_fee_plan,
    read_csv,
)

COUNT = 5_000


@pytest.fixture(scope="module")
def data():
    payments, lines, answer_key = generate(seed=42, count=COUNT)
    return {
        "payments": {p["payment_id"]: p for p in payments},
        "lines": lines,
        "key": answer_key,
        "holidays": load_bank_holidays(),
        "rates": load_rates(),
        "merchants": {m["merchant_id"]: m for m in read_csv(SEEDS_DIR / "merchants.csv")},
        "fee_plans": read_csv(SEEDS_DIR / "fee_plans.csv"),
    }


def lines_for(data, payment_id):
    """The provider lines for a payment, matching ids the way a careful person would (trim, upper case)."""
    return [line for line in data["lines"] if line["payment_id"].strip().upper() == payment_id]


def keys_of_type(data, problem_type):
    return [row for row in data["key"] if row["problem_type"] == problem_type]


def created(data, payment_id):
    return date.fromisoformat(data["payments"][payment_id]["created_at"][:10])


def test_same_seed_gives_same_data_and_answer_key(data):
    assert generate(seed=42, count=COUNT) == (list(data["payments"].values()), data["lines"], data["key"])


def test_planted_counts_match_the_rates(data):
    counts = Counter(row["problem_type"] for row in data["key"])
    refund_types = [t for t in counts if t.startswith(("refund", "chargeback"))]
    for refund_type in refund_types:
        del counts[refund_type]
    assert counts == {
        "fx": 15,
        "missing": 30,
        "duplicate": 20,
        "fee": 20,
        "late": 20,
        "messy_id": 15,
        "unrecorded": 10,
    }


def test_each_payment_has_at_most_one_problem(data):
    ids = [row["payment_id"] for row in data["key"]]
    assert len(ids) == len(set(ids))


def test_problems_are_only_planted_on_early_enough_payments(data):
    for row in data["key"]:
        if row["problem_type"] != "unrecorded":
            assert created(data, row["payment_id"]) <= LAST_PROBLEM_DATE


def test_missing_payments_have_no_provider_line(data):
    for row in keys_of_type(data, "missing"):
        assert lines_for(data, row["payment_id"]) == []


def test_duplicates_have_two_lines_with_different_references(data):
    for row in keys_of_type(data, "duplicate"):
        lines = lines_for(data, row["payment_id"])
        assert len(lines) == 2
        assert lines[0]["provider_reference"] != lines[1]["provider_reference"]


def test_fee_problems_have_a_clearly_wrong_fee(data):
    for row in keys_of_type(data, "fee"):
        payment = data["payments"][row["payment_id"]]
        merchant = data["merchants"][payment["merchant_id"]]
        (line,) = lines_for(data, row["payment_id"])
        plan = pick_fee_plan(data["fee_plans"], merchant["fee_tier"], merchant["settlement_currency"], created(data, row["payment_id"]))
        right_fee = calculate_fee(line["gross_minor_units"], plan)
        assert abs(line["fee_minor_units"] - right_fee) >= 2
        assert line["net_minor_units"] == line["gross_minor_units"] - line["fee_minor_units"]


def test_fx_problems_use_a_rate_more_than_half_a_percent_out(data):
    for row in keys_of_type(data, "fx"):
        payment = data["payments"][row["payment_id"]]
        merchant = data["merchants"][payment["merchant_id"]]
        (line,) = lines_for(data, row["payment_id"])
        ecb_rate = fx_rate(data["rates"], payment["currency"], merchant["settlement_currency"], date.fromisoformat(line["settlement_date"]))
        assert abs(float(line["fx_rate"]) / float(ecb_rate) - 1) > 0.005


def test_late_problems_settle_after_two_business_days(data):
    for row in keys_of_type(data, "late"):
        (line,) = lines_for(data, row["payment_id"])
        on_time = add_business_days(created(data, row["payment_id"]), 2, data["holidays"])
        assert date.fromisoformat(line["settlement_date"]) > on_time


def test_unrecorded_lines_are_for_payments_not_in_the_ledger(data):
    for row in keys_of_type(data, "unrecorded"):
        assert row["payment_id"] not in data["payments"]
        assert len(lines_for(data, row["payment_id"])) == 1


def test_messy_ids_differ_as_written_but_match_once_cleaned(data):
    for row in keys_of_type(data, "messy_id"):
        (line,) = lines_for(data, row["payment_id"])
        assert line["payment_id"] != row["payment_id"]
        assert line["payment_id"].strip().upper() == row["payment_id"]


def test_untouched_payments_are_settled_correctly_or_still_pending(data):
    problem_ids = {row["payment_id"] for row in data["key"]}
    for payment_id, payment in data["payments"].items():
        if payment_id in problem_ids:
            continue
        lines = lines_for(data, payment_id)
        if not lines:
            # Nothing arrived and nothing was planted, so it must simply be too recent to have settled.
            assert created(data, payment_id) > LAST_PROBLEM_DATE
            continue
        (line,) = lines
        merchant = data["merchants"][payment["merchant_id"]]
        plan = pick_fee_plan(data["fee_plans"], merchant["fee_tier"], merchant["settlement_currency"], created(data, payment_id))
        assert line["fee_minor_units"] == calculate_fee(line["gross_minor_units"], plan)
        settled = date.fromisoformat(line["settlement_date"])
        assert settled in {add_business_days(created(data, payment_id), n, data["holidays"]) for n in (1, 2)}
        assert line["payment_id"] == payment_id  # clean ids


def test_no_provider_line_is_dated_after_the_data_ends(data):
    assert all(line["settlement_date"] <= END_DATE.isoformat() for line in data["lines"])


def test_provider_references_are_unique(data):
    references = [line["provider_reference"] for line in data["lines"]]
    assert len(references) == len(set(references))


# ---------- Refunds and chargebacks ----------


def refund_rows(data):
    return [row for row in data["key"] if row["problem_type"].startswith(("refund", "chargeback"))]


def test_refund_and_chargeback_counts(data):
    counts = Counter(row["problem_type"].split("_")[0] for row in refund_rows(data))
    assert counts == {"refund": 100, "chargeback": 15}  # 2% and 0.3% of 5,000 payments


def test_refunds_are_negative_ledger_rows_linked_to_a_real_payment(data):
    for row in refund_rows(data):
        item = data["payments"][row["payment_id"]]
        original = data["payments"][item["linked_payment_id"]]
        assert item["payment_type"] == row["problem_type"].split("_")[0]
        assert original["payment_type"] == "payment"
        assert item["amount_minor_units"] == -original["amount_minor_units"]
        assert item["currency"] == original["currency"]
        assert created(data, row["payment_id"]) > created(data, original["payment_id"])


def test_originals_of_refunds_had_no_other_problem(data):
    other_problem_ids = {row["payment_id"] for row in data["key"] if row not in refund_rows(data)}
    for row in refund_rows(data):
        assert data["payments"][row["payment_id"]]["linked_payment_id"] not in other_problem_ids


def test_each_payment_is_refunded_at_most_once(data):
    linked = [p["linked_payment_id"] for p in data["payments"].values() if p["linked_payment_id"]]
    assert len(linked) == len(set(linked))


def test_settled_refunds_are_negative_lines_with_no_fee(data):
    for row in refund_rows(data):
        lines = lines_for(data, row["payment_id"])
        if row["problem_type"].endswith("_settled"):
            (line,) = lines
            assert line["gross_minor_units"] < 0
            assert line["fee_minor_units"] == 0
            assert line["net_minor_units"] == line["gross_minor_units"]
            assert row["expected_status"] == "Matched"
        else:
            assert lines == []
            assert row["expected_status"] == "Missing settlement"


def test_ledger_is_in_time_order(data):
    created_times = [p["created_at"] for p in data["payments"].values()]
    assert created_times == sorted(created_times)
