"""Tests for the ECB rates script. They use a tiny made-up file, so no internet is needed."""

from download_ecb_rates import pick_rates, write_rates

# Newest date first, like the real ECB file. The trailing comma on the header is real too.
FAKE_ECB_CSV = """Date,USD,JPY,GBP,SEK,ZAR,
2026-12-01,1.10,175.0,0.84,11.3,20.0,
2026-06-02,1.07,172.0,0.85,N/A,19.5,
2026-06-01,1.06,171.0,0.86,11.0,19.4,
2026-05-29,1.05,170.0,0.87,10.9,19.3,
"""


def test_keeps_only_dates_in_range():
    rows = pick_rates(FAKE_ECB_CSV, "2026-06-01", "2026-11-30", ["GBP"])
    assert [row["rate_date"] for row in rows] == ["2026-06-01", "2026-06-02"]


def test_keeps_only_requested_currencies():
    rows = pick_rates(FAKE_ECB_CSV, "2026-06-01", "2026-11-30", ["GBP", "JPY"])
    assert {row["currency"] for row in rows} == {"GBP", "JPY"}


def test_skips_missing_rates():
    rows = pick_rates(FAKE_ECB_CSV, "2026-06-01", "2026-11-30", ["SEK"])
    assert rows == [{"rate_date": "2026-06-01", "currency": "SEK", "rate_per_eur": "11.0"}]


def test_rates_are_kept_exactly_as_written():
    rows = pick_rates(FAKE_ECB_CSV, "2026-06-02", "2026-06-02", ["JPY"])
    assert rows[0]["rate_per_eur"] == "172.0"


def test_write_rates_writes_header_and_rows(tmp_path):
    rows = pick_rates(FAKE_ECB_CSV, "2026-06-01", "2026-06-01", ["GBP"])
    output_file = tmp_path / "out" / "rates.csv"
    write_rates(rows, output_file)
    assert output_file.read_text().splitlines() == [
        "rate_date,currency,rate_per_eur",
        "2026-06-01,GBP,0.86",
    ]
