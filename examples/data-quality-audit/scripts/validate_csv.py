#!/usr/bin/env python3
"""Read-only CSV quality validator; Python 3.9+, standard library only.

Usage:
  python3 scripts/validate_csv.py --file data.csv --required id,amount --keys id --numeric amount

Prints JSON result to stdout. Exit: 0 clean, 1 quality issues, 2 invalid input/config.
Does not modify the input file or create any other files.
"""
import argparse
import csv
import json
import sys
from pathlib import Path


def split_columns(csv_value):
    return [c.strip() for c in csv_value.split(",") if c.strip()]


def check_file(file_path, required, keys, numeric, min_rows=1, delimiter=","):
    result = {"file": str(file_path), "rows_checked": 0, "columns": [], "checks": {"required": required, "keys": keys, "numeric": numeric, "min_rows": min_rows}, "issues": [], "status": "fail"}
    if not file_path.is_file():
        raise ValueError("CSV input not found: %s. Fix: pass an existing file using --file." % file_path)
    try:
        with file_path.open("r", encoding="utf-8-sig", newline="") as fp:
            reader = csv.DictReader(fp, delimiter=delimiter)
            fields = reader.fieldnames or []
            if len(fields) != len(set(fields)):
                result["issues"].append({"row": 1, "type": "duplicate-header", "message": "duplicate column names in CSV header"})
            result["columns"] = fields
            for col in sorted(set(required + keys + numeric)):
                if col not in fields:
                    result["issues"].append({"row": 1, "column": col, "type": "missing-column", "message": "required check column '%s' is not in CSV header; columns available: %s" % (col, ", ".join(fields))})
            found = {}
            for row_number, row in enumerate(reader, start=2):
                result["rows_checked"] += 1
                if None in row:
                    result["issues"].append({"row": row_number, "type": "extra-fields", "message": "CSV row has more fields than header"})
                for col in required:
                    if col in fields and not str(row.get(col) or "").strip():
                        result["issues"].append({"row": row_number, "column": col, "type": "blank-required", "message": "required field is empty"})
                if keys and all(k in fields for k in keys):
                    composite = tuple(row.get(k) for k in keys)
                    if composite in found:
                        result["issues"].append({"row": row_number, "type": "duplicate-key", "message": "same key as CSV row %d" % found[composite], "columns": keys})
                    else:
                        found[composite] = row_number
                for col in numeric:
                    if col in fields:
                        value = str(row.get(col) or "").strip()
                        if value:
                            try:
                                float(value)
                            except ValueError:
                                result["issues"].append({"row": row_number, "column": col, "type": "invalid-numeric", "message": "not a parseable number"})
    except (UnicodeError, csv.Error, OSError) as exc:
        raise ValueError("Could not parse CSV %s: %s. Fix: provide UTF-8 CSV with valid delimiter." % (file_path, exc))
    if result["rows_checked"] < min_rows:
        result["issues"].append({"row": 0, "type": "min-rows", "message": "row count %d below minimum %d" % (result["rows_checked"], min_rows)})
    result["status"] = "pass" if not result["issues"] else "fail"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate CSV schema, keys, missingness and numeric values without editing it")
    parser.add_argument("--file", required=True)
    parser.add_argument("--required", default="", help="comma-separated required columns")
    parser.add_argument("--keys", default="", help="comma-separated unique-key columns")
    parser.add_argument("--numeric", default="", help="comma-separated numeric columns")
    parser.add_argument("--min-rows", type=int, default=1)
    parser.add_argument("--delimiter", default=",")
    args = parser.parse_args(argv)
    if args.min_rows < 0 or len(args.delimiter) != 1:
        parser.error("--min-rows must be >=0 and --delimiter must be a single character")
    try:
        result = check_file(Path(args.file).expanduser(), split_columns(args.required), split_columns(args.keys), split_columns(args.numeric), args.min_rows, args.delimiter)
    except ValueError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
