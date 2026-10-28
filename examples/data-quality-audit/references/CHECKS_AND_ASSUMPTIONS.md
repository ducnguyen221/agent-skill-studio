# Data Quality Checks & Assumptions

## Data grain

Clarify a business key before treating duplicates as defects. A sales line can be legitimately repeated by order ID if grain is **order line**, not order header. For analytics/Fabric/Power BI, do not infer relationship cardinality from sample rows alone.

## Checks supported by the bundled script

- Required columns exist in the CSV header.
- Required values are not blank on each row.
- Composite key uniqueness across supplied `--keys`.
- Numeric columns contain parseable numeric values if requested via `--numeric`.
- At least `--min-rows` rows exist (default 1).
- File/CSV parsing and unexpected encoding errors are reported.

## Scope exclusions

The script does not verify referential integrity to another table, detect bias, infer missing business rules, or validate DAX correctness. A clean result only means the **specified checks** passed, not that the dataset is suitable for every decision.

## Recommended reporting format (flexible)

```text
Dataset | Grain & required fields | Checks performed | Issues (row/column) | Evidence | Recommendations | Limitations
```

Use row numbers tied to CSV data lines when showing errors. Avoid reproducing sensitive values in public reports.
