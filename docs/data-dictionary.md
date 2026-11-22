# Data dictionary

All data is invented by `generator/generate_data.py` (seed 42). Nothing comes from a real company. Dates run from Monday 1 June to Friday 20 November 2026, which is the "as of" date: the reconciliation is run as if it were the end of that day.

Amounts are whole numbers in **minor units**: pence, cents and öre have two decimal places, yen has none. So `amount_minor = 7486` in USD is $74.86, and `amount_minor = 7486` in JPY is ¥7,486.

## Source files (loaded via the bucket into `payrecon_raw`)

### `payments/payments_YYYYMMDD.csv` → `payrecon_raw.payments`

The company's own ledger: one file per calendar day, one row per payment, refund or chargeback. 48,905 rows.

| Column | Meaning |
| --- | --- |
| `payment_id` | internal id, `PAY-0000001` onwards |
| `merchant_id` | merchant the payment belongs to |
| `payment_type` | `PAYMENT` (47,386), `REFUND` (1,338) or `CHARGEBACK` (181) |
| `original_payment_id` | for refunds and chargebacks, the payment being reversed |
| `currency` | currency the customer paid in: GBP, EUR, USD, SEK or JPY |
| `amount_minor` | negative for refunds and chargebacks |
| `created_at` | when it was taken, UTC |
| `card_scheme` | VISA, MASTERCARD or AMEX |

### `settlements/settlement_YYYYMMDD.csv` → `payrecon_raw.settlement_lines`

The payment provider's settlement files: one per UK business day (weekends and UK bank holidays have no file). 48,365 rows.

| Column | Meaning |
| --- | --- |
| `provider_ref` | provider's unique id for the line |
| `settlement_date` | date of the file |
| `merchant_id` | merchant paid |
| `payment_id` | our id as the provider recorded it; some have trailing spaces or lower case and should still match |
| `transaction_type` | `CAPTURE`, `REFUND` or `CHARGEBACK` |
| `presentment_currency`, `presentment_amount_minor` | what the customer paid |
| `settlement_currency` | what the merchant is paid in: GBP, EUR or USD |
| `fx_rate` | settlement currency units per one unit of presentment currency, 6 decimal places |
| `gross_amount_minor` | presentment amount × fx_rate, rounded half away from zero |
| `fee_amount_minor` | provider fee |
| `net_amount_minor` | gross minus fee: what the merchant receives |

### `fx_rates/fx_rates.csv` → `payrecon_raw.fx_rates`

Daily reference rates in the ECB style: units of each currency per 1 euro, published on weekdays only. Simulated, not the real ECB figures. 520 rows (GBP, USD, SEK and JPY from 25 May).

To get a rate between two non-euro currencies, go through the euro: GBP per USD = (GBP per EUR) ÷ (USD per EUR). On days without a rate, use the last published one.

### `merchants/merchants.csv` → `payrecon_raw.merchants`

40 invented merchants: 20 in the UK (paid in GBP), 12 in Ireland, Germany, France and the Netherlands (EUR), 8 in the US (USD), each on one fee plan.

### `answer_key/answer_key.csv` → `payrecon_raw.answer_key`

The status every record should get. **Only tests may read this table, never models.** One row per payment (`payment_id` set) plus one row per unrecorded settlement line (`provider_ref` set).

| Expected status | Rows |
| --- | --- |
| MATCHED | 47,273 |
| PENDING | 448 |
| MISSING | 331 |
| LATE | 284 |
| AMOUNT_MISMATCH | 235 |
| DUPLICATE | 179 |
| FX_MISMATCH | 155 |
| UNRECORDED | 60 |

`planted_issue` says which problem was planted. A handful of planted problems sit on payments the provider hasn't settled yet, so they correctly show as PENDING.

## Reference tables (dbt seeds in `payments_recon/seeds/`)

| Seed | What it holds |
| --- | --- |
| `fee_plans` | STANDARD (1.40% + 0.20 until 31 Aug 2026, then 1.50% + 0.20), VOLUME (0.95% + 0.10), PREMIUM (2.10% + 0.25); chargebacks cost a flat 15.00 |
| `currencies` | decimal places per currency |
| `uk_bank_holidays` | 2026 UK bank holidays (31 August is the one inside the data period) |

## The rules the data follows

- **Settlement deadline:** within 2 UK business days of the payment's UTC date (the payment day itself counts as day 0).
- **FX:** the provider uses the reference rate for the payment's date (or the last one before it).
- **Fees,** using the fee plan valid on the payment's date: payments pay `round(gross × percentage ÷ 100) + fixed fee`; refunds pay no fee; chargebacks pay the chargeback fee.
- **Statuses,** checked in this order: UNRECORDED, DUPLICATE, MISSING or PENDING (no line yet), AMOUNT_MISMATCH (net ≠ gross − expected fee, more than 1 minor unit out), FX_MISMATCH (rate more than 0.5% from reference), LATE (settled after the deadline), otherwise MATCHED.

`tests/test_generator.py` applies these rules in plain Python and checks the result agrees with the answer key on every row.
