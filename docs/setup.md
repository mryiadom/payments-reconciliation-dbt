# Local setup (macOS)

Copy the commands one at a time. Everything runs from the VS Code terminal (Terminal > New Terminal), inside the repo folder.

## 1. VS Code extensions

- **Python** (Microsoft)
- **Power User for dbt** (Altimate AI): model previews, lineage, go-to-definition for `ref()`
- **sqlfluff**: flags SQL style problems as you type

## 2. Python virtual environment and dbt

```bash
python3 --version              # should be 3.10, 3.11 or 3.12
python3 -m venv .venv          # creates the virtual environment in .venv/
source .venv/bin/activate      # switches it on; prompt now starts with (.venv)
pip install --upgrade pip
pip install dbt-bigquery
dbt --version
```

Run `source .venv/bin/activate` again in every new terminal. If VS Code asks "We noticed a new environment… select it for the workspace?", click Yes (or run "Python: Select Interpreter" and pick `.venv`).

## 3. Google Cloud sign-in

```bash
gcloud --version               # if "command not found", install the CLI first:
                               # https://cloud.google.com/sdk/docs/install
gcloud auth application-default login
```

A browser opens: sign in with the Google account that owns the GCP project.

## 4. BigQuery datasets

In the Google Cloud console, open BigQuery, click the three dots next to your project, then Create dataset. Create:

- `raw`
- `dev`

Use the same location for both: **europe-west2 (London)**. Note your **project ID** from the project picker (it can differ from the project name).

## 5. dbt project

From the repo root:

```bash
dbt init payments_recon
```

Answers: `bigquery`, then `oauth`, then your project ID, dataset `dev`, threads `4`, default timeout, location `europe-west2`.

This writes your connection settings to `~/.dbt/profiles.yml` (outside the repo, so nothing private is committed).

```bash
cd payments_recon
dbt debug                      # should end with "All checks passed!"
```

## 6. Commit

In VS Code's Source Control panel, check that `.venv/`, `target/` and `logs/` are not listed (they are ignored), then commit on a new branch and open a pull request. Never commit straight to `main`.
