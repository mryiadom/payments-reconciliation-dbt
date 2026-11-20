# payments-reconciliation-dbt

Payments reconciliation in dbt on BigQuery: matches a payment provider's settlement files to internal payment records, with tests and CI.

Work in progress. See:

- [Project plan](docs/project-plan.md): the business problem, design, matching rules, tests and schedule
- [Local setup](docs/setup.md): Python, dbt and BigQuery on macOS

All data in this project is generated, apart from public ECB FX rates.
