# Working in this repo

Portfolio project: payments reconciliation in dbt Core on BigQuery. The full plan is in `docs/project-plan.md`; local setup is in `docs/setup.md`.

## How to help

- The owner is learning dbt and is newer to Python. Explain what each piece of code does in plain English, and prefer simple, readable code over clever code. The owner must be able to explain every line in an interview.
- Suggest small changes, one pull request at a time, each tied to a task in the plan's schedule.
- Never commit to `main`. Work on a branch and open a pull request with a description (what, why, how tested).
- Before writing any code, explain the plan in plain English and wait for the owner's OK.
- Explain each step as you go: what it does and why.
- For commands, show them and let the owner run them.
- After each piece of work, give the owner 3 questions an interviewer might ask about it, with short answers.

## Conventions

- UK English in docs, comments and descriptions.
- dbt layers: `stg_` (views, one per source), `int_` (tables), `fct_` / `dim_` / `rpt_` (marts, tables with contracts).
- Every model and mart column gets a description and tests in its yml file.
- Tolerances and business-day limits are dbt variables in `dbt_project.yml`, not hard-coded.
- Amounts are stored in minor units; JPY has zero decimal places.

## Hard rules

- All data is generated or public (ECB FX rates). Never add real company data, client names, or code from any employer.
- No secrets or service account keys in the repo. Connection settings live in `~/.dbt/profiles.yml`.
- The `answer_key` table is used only by tests, never by models.
