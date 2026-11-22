"""Tests for the data generator.

The most important test, test_answer_key_matches_the_rules, re-runs the matching
rules from docs/project-plan.md in plain Python. If it passes, the data and the
answer key agree with the rules, so a correct dbt model can reach 100%.

Run from the repo root:  pytest
"""

import csv
import hashlib
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "generator"))
import generate_data as g  # noqa: E402

FX_TOLERANCE = Decimal("0.005")   # 0.5%
AMOUNT_TOLERANCE_MINOR = 1


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    seeds = tmp_path_factory.mktemp("seeds")
    summary = g.generate(g.DEFAULT_SEED, out, seeds)
    return out, seeds, summary


def read_folder(folder: Path) -> list[dict]:
    rows = []
    for path in sorted(folder.glob("*.csv")):
        with path.open(encoding="utf-8") as f:
            rows.extend(csv.DictReader(f))
    return rows


def folder_hash(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*.csv")):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_same_seed_gives_same_files(generated, tmp_path):
    out, _, _ = generated
    g.generate(g.DEFAULT_SEED, tmp_path / "again", tmp_path / "seeds")
    assert folder_hash(out) == folder_hash(tmp_path / "again")


def test_one_settlement_file_per_business_day(generated):
    out, _, _ = generated
    expected = {f"settlement_{d:%Y%m%d}.csv" for d in g.daterange(g.START_DATE, g.AS_OF_DATE) if g.is_business_day(d)}
    assert {p.name for p in (out / "settlements").glob("*.csv")} == expected


def test_net_is_gross_minus_fee_on_every_line(generated):
    out, _, _ = generated
    for line in read_folder(out / "settlements"):
        assert int(line["net_amount_minor"]) == int(line["gross_amount_minor"]) - int(line["fee_amount_minor"])


def test_every_problem_type_is_planted(generated):
    _, _, summary = generated
    for status in ["MISSING", "DUPLICATE", "AMOUNT_MISMATCH", "FX_MISMATCH", "LATE", "PENDING", "UNRECORDED"]:
        assert summary.get(status, 0) > 0, status
    planted = summary["payments"] - summary["MATCHED"] - summary["PENDING"]
    assert 0.01 < planted / summary["payments"] < 0.05


def test_answer_key_matches_the_rules(generated):
    out, seeds, _ = generated
    payments = {p["payment_id"]: p for p in read_folder(out / "payments")}
    merchants = {m["merchant_id"]: m for m in read_folder(out / "merchants")}
    with (seeds / "fee_plans.csv").open(encoding="utf-8") as f:
        fee_plans = list(csv.DictReader(f))
    rates = defaultdict(dict)
    for r in read_folder(out / "fx_rates"):
        rates[date.fromisoformat(r["rate_date"])][r["currency"]] = Decimal(r["rate_per_eur"])
    for day_rates in rates.values():
        day_rates["EUR"] = Decimal(1)

    lines_by_payment = defaultdict(list)
    actual = {}
    for line in read_folder(out / "settlements"):
        clean_id = line["payment_id"].strip().upper()
        if clean_id not in payments:
            actual[line["provider_ref"]] = "UNRECORDED"
        else:
            lines_by_payment[clean_id].append(line)

    for payment_id, p in payments.items():
        created = date.fromisoformat(p["created_at"][:10])
        due = g.add_business_days(created, g.SETTLEMENT_DAYS)
        lines = lines_by_payment.get(payment_id, [])
        if len(lines) > 1:
            actual[payment_id] = "DUPLICATE"
            continue
        if not lines:
            actual[payment_id] = "MISSING" if due <= g.AS_OF_DATE else "PENDING"
            continue
        line = lines[0]
        gross, net = int(line["gross_amount_minor"]), int(line["net_amount_minor"])
        plan = next(
            fp for fp in fee_plans
            if fp["fee_plan_code"] == merchants[p["merchant_id"]]["fee_plan_code"]
            and date.fromisoformat(fp["valid_from"]) <= created <= date.fromisoformat(fp["valid_to"])
        )
        if p["payment_type"] == "PAYMENT":
            fee = g.round_half_away(Decimal(gross) * Decimal(plan["percentage_fee"]) / 100) + int(plan["fixed_fee_minor"])
        elif p["payment_type"] == "CHARGEBACK":
            fee = int(plan["chargeback_fee_minor"])
        else:
            fee = 0
        day_rates = rates[max(d for d in rates if d <= created)]
        reference = day_rates[line["settlement_currency"]] / day_rates[p["currency"]]

        if abs(net - (gross - fee)) > AMOUNT_TOLERANCE_MINOR:
            actual[payment_id] = "AMOUNT_MISMATCH"
        elif abs(Decimal(line["fx_rate"]) / reference - 1) > FX_TOLERANCE:
            actual[payment_id] = "FX_MISMATCH"
        elif date.fromisoformat(line["settlement_date"]) > due:
            actual[payment_id] = "LATE"
        else:
            actual[payment_id] = "MATCHED"

    expected = {}
    for row in read_folder(out / "answer_key"):
        expected[row["payment_id"] or row["provider_ref"]] = row["expected_status"]

    wrong = {k: (expected[k], actual.get(k)) for k in expected if expected[k] != actual.get(k)}
    assert not wrong, f"{len(wrong)} records disagree, for example {list(wrong.items())[:5]}"
    assert set(actual) == set(expected)
