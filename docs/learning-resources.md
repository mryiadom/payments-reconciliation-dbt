# Learning resources

Matched to the weeks in the [project plan](project-plan.md). Watch or read each one just before the week that needs it, not all at once.

| When | What | Format | Why |
| --- | --- | --- | --- |
| Before week 1 | [dbt Fundamentals](https://learn.getdbt.com/courses/dbt-fundamentals) (dbt Labs) | video course on dbt Learn | models, sources, tests, docs, `ref()`; the core of the whole project |
| Week 1 | [Loading CSV data from Cloud Storage](https://docs.cloud.google.com/bigquery/docs/loading-data-cloud-storage-csv) (Google) | docs | what `bq load`, schemas and `--replace` do |
| Week 1 | [GitHub Actions quickstart](https://docs.github.com/en/actions/quickstart) (GitHub) | docs, 10 minutes | how a workflow file runs on each pull request |
| Week 1 | [google-github-actions/auth](https://github.com/google-github-actions/auth) | README | signing GitHub Actions in to Google Cloud |
| Week 2 | [How we structure our dbt projects](https://docs.getdbt.com/best-practices/how-we-structure/1-guide-overview) (dbt Labs) | guide | staging, intermediate and marts, and why |
| Week 2 | [Data tests](https://docs.getdbt.com/docs/build/data-tests) (dbt docs) | docs | generic and singular tests |
| Week 2 | Kimball, *The Data Warehouse Toolkit*, chapters 1 to 3 | book | facts, dimensions and grain: the star schema questions interviewers ask |
| Week 3 | [Unit tests](https://docs.getdbt.com/docs/build/unit-tests) (dbt docs) | docs | testing the status logic on hand-written rows; needs dbt 1.8 or later |
| Week 3 | [Model contracts](https://docs.getdbt.com/docs/mesh/govern/model-contracts) (dbt docs) | docs | enforced column types on the marts |

Links checked on 22 November 2026: all load. If one moves, search the title on the same site.
