# Working in this repo

Portfolio project: an end-to-end payments reconciliation on Google Cloud. Generated CSVs (`data/`) are uploaded to a Cloud Storage bucket, loaded into BigQuery (`payrecon_raw`), and reconciled in dbt Core (`payments_recon/`). Read `docs/project-plan.md`, `docs/setup.md` and `docs/data-dictionary.md` before helping.

## How to help

- The owner is learning dbt and is newer to Python. Before writing code, explain the plan in plain English and wait for an OK. Explain each step: what it does and why.
- For commands (gcloud, bq, dbt, git), show them and let the owner run them.
- Prefer simple, readable SQL and code over clever code. The owner must be able to explain every line in an interview.
- After each piece of work, give 3 questions an interviewer might ask about it, with short answers.
- One small pull request at a time, each tied to a task in the plan's schedule.
- Never commit to `main`. Work on a branch and open a pull request with a description (what, why, how tested).

## Names (do not invent others)

- Region `europe-west2`; bucket `PROJECT_ID-payrecon-landing`
- Raw dataset `payrecon_raw` with tables `payments`, `settlement_lines`, `fx_rates`, `merchants`, `answer_key`
- dbt profile and project `payments_recon`; datasets `payrecon_dev`, `payrecon_ci_pr_<n>`, `payrecon_prod`
- Seeds `fee_plans`, `currencies`, `uk_bank_holidays`

## Conventions

- UK English in docs, comments and descriptions.
- dbt layers: `stg_` (views, one per source), `int_` (tables), `fct_` / `dim_` / `rpt_` (marts, tables with contracts).
- Every model and mart column gets a description and tests in its yml file.
- Business rules (as-of date, settlement days, tolerances) are dbt variables in `dbt_project.yml`, not hard-coded.
- Amounts are integers in minor units; JPY has zero decimal places.

## Hard rules

- All data is generated. Never add real company data, client names, or code from any employer.
- Do not edit files in `data/` by hand; change `generator/generate_data.py` and re-run it, then re-run `pytest`.
- No secrets or service account keys in the repo. dbt connection settings live in `~/.dbt/profiles.yml`.
- `payrecon_raw.answer_key` is read only by tests, never by models.
