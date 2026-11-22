# Setup: from CSV files to BigQuery and dbt

The data is already generated and sits in the `data/` folder of this repo. Your job in this guide is to land it in Google Cloud the way a real pipeline would: files into a Cloud Storage bucket, then from the bucket into BigQuery raw tables. After that, dbt takes over.

```
data/ (this repo)  ->  Cloud Storage bucket  ->  BigQuery payrecon_raw  ->  dbt  ->  payrecon_dev
```

Everything in this guide is done in the browser. No terminal is needed. If you would rather work on your laptop with a terminal, see [the laptop option](#option-work-on-your-laptop-terminal-and-dbt-core) at the end.

## Where you work

| Tool | Used for |
| --- | --- |
| Google Cloud console | the bucket, the datasets, loading the raw tables, the service account |
| dbt Cloud (Studio IDE) | writing models and tests, running dbt, branches and commits |
| GitHub | pull requests, merging, and the CI workflow file |

## Names to use

Replace `PROJECT_ID` everywhere with your Google Cloud project ID (find it in the project picker at the top of the console; it can differ from the project name).

| Thing | Name | Notes |
| --- | --- | --- |
| Region | `europe-west2` (London) | use it for the bucket and every dataset; BigQuery can't load across regions |
| Bucket | `PROJECT_ID-payrecon-landing` | bucket names are global, so the project ID keeps it unique |
| Bucket folders | `payments/`, `settlements/`, `fx_rates/`, `merchants/`, `answer_key/` | one folder per source, as in `data/` |
| Raw dataset | `payrecon_raw` | tables loaded from the bucket, never edited by hand |
| Dev dataset | `payrecon_dev` | where dbt builds while you develop |
| Prod dataset | `payrecon_prod` | built only from `main` by CI, later in the project |
| Raw tables | `payments`, `settlement_lines`, `fx_rates`, `merchants`, `answer_key` | all in `payrecon_raw` |
| Service account | `payrecon-dbt-cloud` | how dbt Cloud signs in to BigQuery |
| dbt project | `payments_recon` | folder `payments_recon/` in this repo |

## 1. Create the bucket and upload the files

1. Cloud Storage > Buckets > **Create**.
2. Name: `PROJECT_ID-payrecon-landing`. Location type: **Region**, then `europe-west2 (London)`. Leave everything else as it is, and create it.
3. Open the bucket and click **Upload folder** once for each of the five folders in `data/`: `payments`, `settlements`, `fx_rates`, `merchants`, `answer_key`. (Get them from the repo you cloned, or download the repo as a ZIP from GitHub: Code > Download ZIP.)

Check: five folders, with 173 files in `payments/` and 124 in `settlements/`.

If creating the bucket asks for billing, link a billing account to the project. Cloud Storage needs one even inside the free allowance.

## 2. Create the datasets

In BigQuery, click the three dots next to your project > **Create dataset**. Do it twice:

- Dataset ID `payrecon_raw`, location type **Region**, `europe-west2`
- Dataset ID `payrecon_dev`, same region

## 3. Load the bucket into BigQuery

Each load takes every file in one bucket folder and puts it into one table, with the column types from `load/schemas/`.

Click the three dots next to `payrecon_raw` > **Create table**, and fill it in like this:

| Field | Value |
| --- | --- |
| Create table from | Google Cloud Storage |
| Select file from bucket or use a URI pattern | the path from the table below, with the `*.csv` wildcard |
| File format | CSV |
| Dataset | `payrecon_raw` |
| Table | the table name from the table below |
| Schema | turn on **Edit as text**, then paste the whole schema file (open it on GitHub and use the copy button) |
| Advanced options > Header rows to skip | `1` |

Do this five times:

| Table | Path in the bucket | Schema file |
| --- | --- | --- |
| `payments` | `PROJECT_ID-payrecon-landing/payments/*.csv` | [`load/schemas/payments.json`](../load/schemas/payments.json) |
| `settlement_lines` | `PROJECT_ID-payrecon-landing/settlements/*.csv` | [`load/schemas/settlement_lines.json`](../load/schemas/settlement_lines.json) |
| `fx_rates` | `PROJECT_ID-payrecon-landing/fx_rates/*.csv` | [`load/schemas/fx_rates.json`](../load/schemas/fx_rates.json) |
| `merchants` | `PROJECT_ID-payrecon-landing/merchants/*.csv` | [`load/schemas/merchants.json`](../load/schemas/merchants.json) |
| `answer_key` | `PROJECT_ID-payrecon-landing/answer_key/*.csv` | [`load/schemas/answer_key.json`](../load/schemas/answer_key.json) |

Note that the `settlements/` folder loads into a table called `settlement_lines`.

To reload a table later, do the same again and set **Write preference** (under Advanced options) to **Overwrite table**, so the rows are replaced rather than doubled.

Check the row counts in a new BigQuery query tab:

```sql
select 'payments' as table_name, count(*) as row_count from payrecon_raw.payments
union all select 'settlement_lines', count(*) from payrecon_raw.settlement_lines
union all select 'fx_rates', count(*) from payrecon_raw.fx_rates
union all select 'merchants', count(*) from payrecon_raw.merchants
union all select 'answer_key', count(*) from payrecon_raw.answer_key
```

Expected: payments 48,905 · settlement_lines 48,365 · fx_rates 520 · merchants 40 · answer_key 48,965.

## 4. A service account for dbt Cloud

dbt Cloud needs its own login to your BigQuery.

1. IAM & Admin > Service Accounts > **Create service account**. Name: `payrecon-dbt-cloud`.
2. Grant it two roles: **BigQuery Data Editor** (create and change tables) and **BigQuery Job User** (run queries).
3. Open the account > Keys > Add key > Create new key > **JSON**. A file downloads.
4. Keep that file out of the repo folder. You upload it to dbt Cloud in the next step, then delete it from your Downloads.

## 5. Set up dbt Cloud

Sign up for the free Developer plan at getdbt.com, then create a project:

| Setting | Value |
| --- | --- |
| Project name | `payments_recon` |
| Connection | BigQuery: upload the JSON key; location `europe-west2` |
| Development credentials: dataset | `payrecon_dev` |
| Repository | GitHub (install dbt's GitHub app when asked) > `mryiadom/payments-reconciliation-dbt` |
| Project subdirectory | `payments_recon` (Account settings > Projects > your project > Edit) |
| dbt version | the latest release offered |

The project subdirectory matters: the dbt project sits in the `payments_recon/` folder of the repo, not at the top, and dbt Cloud won't find it without this setting.

## 6. First run

Open the Studio IDE. Create a branch with the git button, then type in the command bar at the bottom:

```
dbt debug
dbt seed
```

`dbt debug` checks the connection. `dbt seed` loads `fee_plans`, `currencies` and `uk_bank_holidays` into `payrecon_dev`. When those three tables appear in BigQuery, setup is done. Next is week 1's modelling work in the [project plan](project-plan.md).

## 7. Branches and pull requests

Never commit to `main`. For each piece of work:

1. In the Studio IDE, create a branch with the git button (for example `feature/sources`).
2. Do the work, run it, then commit with the git button.
3. Open the pull request on GitHub, check CI passes, and merge it there.
4. Back in the IDE, switch to `main` and pull, then start the next branch.

CI on GitHub Actions runs dbt Core and `pytest` on every pull request, whichever editor you use.

## Option: work on your laptop (terminal and dbt Core)

The same project works from a terminal, with dbt Core instead of dbt Cloud. No dbt account is needed.

```bash
git clone https://github.com/mryiadom/payments-reconciliation-dbt
cd payments-reconciliation-dbt
python3 -m venv .venv
source .venv/bin/activate             # run again in every new terminal
pip install -r requirements.txt       # dbt-bigquery and pytest
pytest                                 # 5 tests should pass: the data agrees with the answer key

gcloud auth login                      # for gcloud and bq; install: https://docs.cloud.google.com/sdk/docs/install-sdk
gcloud auth application-default login  # for dbt
gcloud config set project PROJECT_ID
```

Steps 1 to 3 as commands:

```bash
BUCKET=gs://PROJECT_ID-payrecon-landing

gcloud storage buckets create $BUCKET --location=europe-west2 --uniform-bucket-level-access
gcloud storage cp -r data/payments data/settlements data/fx_rates data/merchants data/answer_key $BUCKET/

bq --location=europe-west2 mk --dataset PROJECT_ID:payrecon_raw
bq --location=europe-west2 mk --dataset PROJECT_ID:payrecon_dev

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

`--replace` makes each load safe to repeat: it replaces the table rather than doubling the rows.

Instead of steps 4 to 6, create `~/.dbt/profiles.yml` (outside the repo, so it's never committed):

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

Then `cd payments_recon`, `dbt debug` (should end with "All checks passed!") and `dbt seed`. Branches are the usual `git checkout -b feature/short-description`, then `git push -u origin feature/short-description` and a pull request on GitHub.
