# Setup: from CSV files to BigQuery

The data is already generated and sits in the `data/` folder of this repo. Your job in this guide is to land it in Google Cloud the way a real pipeline would: files into a Cloud Storage bucket, then from the bucket into BigQuery raw tables. After that, dbt takes over.

```
data/ (this repo)  ->  Cloud Storage bucket  ->  BigQuery payrecon_raw  ->  dbt  ->  payrecon_dev
```

## Names to use

Replace `PROJECT_ID` everywhere with your Google Cloud project ID (find it in the project picker at the top of the console; it can differ from the project name).

| Thing | Name | Notes |
| --- | --- | --- |
| Region | `europe-west2` (London) | use it for the bucket and every dataset; BigQuery can't load across regions |
| Bucket | `PROJECT_ID-payrecon-landing` | bucket names are global, so the project ID keeps it unique |
| Bucket folders | `payments/`, `settlements/`, `fx_rates/`, `merchants/`, `answer_key/` | one folder per source, as in `data/` |
| Raw dataset | `payrecon_raw` | tables loaded from the bucket, never edited by hand |
| Dev dataset | `payrecon_dev` | where dbt builds when you run it on your laptop |
| Prod dataset | `payrecon_prod` | built only from `main` by CI, later in the project |
| Raw tables | `payments`, `settlement_lines`, `fx_rates`, `merchants`, `answer_key` | all in `payrecon_raw` |
| dbt project and profile | `payments_recon` | folder `payments_recon/` in this repo |

## 1. Get the repo on your laptop

In VS Code: Clone Git Repository, paste `https://github.com/mryiadom/payments-reconciliation-dbt`, open it. Then in the terminal (Terminal > New Terminal):

```bash
python3 -m venv .venv
source .venv/bin/activate          # prompt now starts with (.venv); run again in every new terminal
pip install --upgrade pip
pip install -r requirements.txt    # dbt-bigquery and pytest
pytest                              # 5 tests should pass: the data agrees with the answer key
```

## 2. Sign in to Google Cloud

```bash
gcloud --version                    # if "command not found": https://cloud.google.com/sdk/docs/install
gcloud auth login                   # for gcloud and bq commands
gcloud auth application-default login   # for dbt
gcloud config set project PROJECT_ID
```

## 3. Create the bucket and upload the files

```bash
gcloud storage buckets create gs://PROJECT_ID-payrecon-landing \
  --location=europe-west2 --uniform-bucket-level-access

gcloud storage cp -r data/payments data/settlements data/fx_rates data/merchants data/answer_key \
  gs://PROJECT_ID-payrecon-landing/
```

Check in the console (Cloud Storage > Buckets): you should see five folders, with 173 files in `payments/` and 124 in `settlements/`.

Console alternative: Cloud Storage > Create bucket (name and region above, everything else default), then drag each folder from `data/` into it.

## 4. Create the datasets

```bash
bq --location=europe-west2 mk --dataset PROJECT_ID:payrecon_raw
bq --location=europe-west2 mk --dataset PROJECT_ID:payrecon_dev
```

Console alternative: BigQuery > three dots next to your project > Create dataset.

## 5. Load the bucket into BigQuery

Each command loads every file in one bucket folder into one table, using the column types in `load/schemas/`. `--replace` means running it again replaces the table rather than doubling the rows, so the load is safe to repeat.

```bash
BUCKET=gs://PROJECT_ID-payrecon-landing

bq load --location=europe-west2 --source_format=CSV --skip_leading_rows=1 --replace \
  payrecon_raw.payments "$BUCKET/payments/*.csv" load/schemas/payments.json

bq load --location=europe-west2 --source_format=CSV --skip_leading_rows=1 --replace \
  payrecon_raw.settlement_lines "$BUCKET/settlements/*.csv" load/schemas/settlement_lines.json

bq load --location=europe-west2 --source_format=CSV --skip_leading_rows=1 --replace \
  payrecon_raw.fx_rates "$BUCKET/fx_rates/*.csv" load/schemas/fx_rates.json

bq load --location=europe-west2 --source_format=CSV --skip_leading_rows=1 --replace \
  payrecon_raw.merchants "$BUCKET/merchants/*.csv" load/schemas/merchants.json

bq load --location=europe-west2 --source_format=CSV --skip_leading_rows=1 --replace \
  payrecon_raw.answer_key "$BUCKET/answer_key/*.csv" load/schemas/answer_key.json
```

Check the row counts in BigQuery:

```sql
select 'payments' as table_name, count(*) as row_count from payrecon_raw.payments
union all select 'settlement_lines', count(*) from payrecon_raw.settlement_lines
union all select 'fx_rates', count(*) from payrecon_raw.fx_rates
union all select 'merchants', count(*) from payrecon_raw.merchants
union all select 'answer_key', count(*) from payrecon_raw.answer_key
```

Expected: payments 48,905 · settlement_lines 48,365 · fx_rates 520 · merchants 40 · answer_key 48,965.

## 6. Connect dbt

Create the file `~/.dbt/profiles.yml` on your laptop (outside the repo, so it's never committed). In the terminal: `mkdir -p ~/.dbt && code ~/.dbt/profiles.yml`, paste this, change `PROJECT_ID`, save:

```yaml
payments_recon:
  target: dev
  outputs:
    dev:
      type: bigquery
      method: oauth
      project: PROJECT_ID
      dataset: payrecon_dev
      location: europe-west2
      threads: 4
      job_execution_timeout_seconds: 300
```

Then:

```bash
cd payments_recon
dbt debug        # should end with "All checks passed!"
dbt seed         # loads fee_plans, currencies and uk_bank_holidays into payrecon_dev
```

Setup is done. Next is week 1's modelling work in the project plan.

## 7. Branches

Never commit to `main`. For each piece of work:

```bash
git checkout main && git pull
git checkout -b feature/short-description
# ... work, then commit in VS Code's Source Control panel ...
git push -u origin feature/short-description
```

Then open a pull request on GitHub and merge it there.
