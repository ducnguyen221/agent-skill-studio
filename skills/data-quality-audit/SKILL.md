---
name: data-quality-audit
description: "Audits CSV data quality for missing required fields, duplicate keys, invalid numeric values and row-count constraints. Use when reviewing tabular CSV inputs before analytics, dashboards, ETL or Power BI reporting."
metadata:
  version: "0.1.0"
  author: "Agent Skill Studio"
---

# Data Quality Audit — CSV

## Critical rules

1. **Read inputs safely**; never modify the source CSV in place.
2. **Validate with an executable script** and report findings including checked rows, failed constraints and relevant evidence.
3. **Data quality depends on business grain.** Confirm which column(s) define unique rows before treating duplicates as errors.
4. **Do not invent schema requirements.** If required columns or keys are unknown, ask or report assumptions explicitly.
5. **Never claim clean data if script failed or was not executed.**

## When to use

For CSV data quality checks prior to ETL, Power BI, report generation or import. Do not invoke for an unrelated marketing writing request or for a Power BI DAX-only explanation that involves no dataset audit.

## Workflow

1. Inspect CSV path, encoding expectation, delimiter and business grain. Done when required columns and keys are known.
2. Read [references/CHECKS_AND_ASSUMPTIONS.md](references/CHECKS_AND_ASSUMPTIONS.md) if data constraints or duplicate semantics are unclear.
3. **Run** `scripts/validate_csv.py --file <path> --required <comma-separated-cols> --keys <comma-separated-cols>`; use `--numeric` only for known numeric columns. Python 3.9+ standard library, no packages to install. Script is read-only. Done when JSON result and exit code are available.
4. Review issues, categorize blockers/warnings and recommend specific source/model changes, not ungrounded repairs.
5. If validation failed, correct the **dataset or check parameters after authorization**, then rerun step 3. Never overwrite original files automatically.
6. Report row count, columns inspected, issue types, file/sample and open assumptions. Done when report cites actual script output.

## Resources

- [references/CHECKS_AND_ASSUMPTIONS.md](references/CHECKS_AND_ASSUMPTIONS.md): Read when deciding business grain, missingness and numeric constraints.
- `scripts/validate_csv.py`: **Run** for deterministic CSV validation. `--help` documents flags; standard library only.
- `assets/sample-data/orders_valid.csv`: Synthetic sample to demonstrate normal execution; not an eval oracle and not customer data.

## Definition of Done

A machine-readable check result has been produced from the requested CSV, all detected issues and unknown assumptions are surfaced, and any critical errors are not silently ignored.
